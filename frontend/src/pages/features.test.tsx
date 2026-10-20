import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Schemas } from '../api/client'
import { LearningsTab } from '../components/repository/LearningsTab'
import { ReviewSettingsTab } from '../components/repository/ReviewSettingsTab'
import { mockApi, renderAt } from '../test/render'
import { AnalyticsPage } from './AnalyticsPage'
import { ReviewQueuePage } from './ReviewQueuePage'

const REPOSITORIES = { items: [{ id: 1, full_name: 'octo/demo', owner: 'octo', default_branch: 'main', html_url: '', is_private: false, last_synced_at: '2026-10-01T10:00:00Z' }], next_cursor: null }

function queueItem(number: number, band: string, priority: number, reviewers: string[] = []): Schemas['QueueItemOut'] {
  return {
    pull_request_id: number, repository_id: 1, repository: 'octo/demo', number, title: `PR ${number}`, author_login: 'alice',
    created_at: '2026-10-01T10:00:00Z', waiting_hours: 50, files_changed: 2, lines_changed: 40, risk_score: 70, risk_level: 'high',
    model_probability: 0.6, effort: { level: 2, minutes: 15 }, priority, band, reasons: ['risk 70 (high)', 'waiting 2 days'],
    review_status: null, findings_shown: 0, findings_high: 0,
    suggested_reviewers: reviewers.map((login) => ({ login, files_touched: 2, last_touched_at: '2026-09-01T10:00:00Z' })),
  }
}

describe('review queue', () => {
  it('lists open PRs in priority order with band, reasons, effort and reviewers', async () => {
    const fetch = mockApi({
      'GET /repositories': [200, REPOSITORIES],
      'GET /review-queue': [200, {
        total: 2140, p1: 30, p2: 900, p3: 1210, total_minutes: 30, not_reviewed: 2000,
        items: [queueItem(10, 'P1', 0.81, ['dave', 'carol']), queueItem(11, 'P3', 0.2)],
      }],
    })
    renderAt('/queue?repository=1', '/queue', <ReviewQueuePage />)

    const rows = within(await screen.findByRole('list', { name: /Pull requests to review/ })).getAllByRole('listitem')
    expect(rows.map((row) => within(row).getByRole('link').textContent)).toEqual(['PR 10', 'PR 11'])
    expect(rows[0]).toHaveTextContent('P1')
    expect(rows[0]).toHaveTextContent('waiting 2 days')
    expect(rows[0]).toHaveTextContent('~15 min')
    expect(within(rows[0]).getByLabelText('Suggested reviewers')).toHaveTextContent('dave carol')
    expect(screen.getByText('30 min')).toBeInTheDocument() // the total estimated review time
    const open = screen.getByText('Open pull requests').closest('.kpi') as HTMLElement
    expect(open).toHaveTextContent('2,140') // every open PR, not just the rows listed
    expect(open).toHaveTextContent('the first 2 are listed')
    const call = fetch.mock.calls.map(([input]) => new URL((input as Request).url)).find((url) => url.pathname === '/review-queue')!
    expect(call.searchParams.get('repository_id')).toBe('1')
  })
})

describe('analytics', () => {
  it('shows acceptance, repeats, learnings and the charts', async () => {
    const category = (name: string, shown: number, useful: number, notUseful: number) => ({
      category: name, shown, useful, not_useful: notUseful, acceptance: useful + notUseful ? useful / (useful + notUseful) : null,
    })
    const fetch = mockApi({
      'GET /repositories': [200, REPOSITORIES],
      'GET /analytics': [200, {
        days: 30, repository_id: null, reviews: 4, reviews_cached: 1, reviews_incremental: 2, cost_usd: 0.12,
        findings_proposed: 10, findings_dropped: 3, findings_shown: 7, votes: { useful: 3, not_useful: 1 }, acceptance: 0.75,
        repeats_after_rejection: 1, learnings_total: 3, learnings_enabled: 2, learnings_proposed: 1, learnings_applied: 5,
        chat_questions: 2, chat_cost_usd: 0.01,
        categories: [category('bug', 3, 2, 0), category('security', 4, 1, 1), category('performance', 0, 0, 0), category('maintainability', 0, 0, 0), category('tests', 0, 0, 0)],
        weeks: [{ week: '2026-10-12', reviews: 4, cost_usd: 0.12, proposed: 10, dropped: 3, shown: 7, useful: 3, not_useful: 1 }],
        models: [{ model: 'qwen', prompt_version: 'review_v2', reviews: 4, cached: 1, avg_cost_usd: 0.04, avg_latency_ms: 2000, findings_shown: 7, findings_dropped: 3, useful: 3, not_useful: 1, acceptance: 0.75 }],
        risk_outcomes: [{ level: 'low', closed: 10, merged: 9, merge_rate: 0.9 }, { level: 'medium', closed: 0, merged: 0, merge_rate: null }, { level: 'high', closed: 4, merged: 1, merge_rate: 0.25 }],
        directories: [{ directory: 'app', findings: 7, high: 2 }],
        drop_reasons: [{ reason: 'quote_not_found', count: 3 }],
        tools: [{ name: 'ruff', runs: 3, findings: 4, skipped: 0 }],
      }],
    })
    renderAt('/analytics?days=30', '/analytics', <AnalyticsPage />)

    expect(await screen.findByRole('img', { name: 'Acceptance and share of findings by category' })).toBeInTheDocument()
    expect(screen.getByText('3 useful of 4 votes')).toBeInTheDocument()
    expect(screen.getByText('1 waiting for approval · used 5×')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Findings shown and dropped per week' })).toBeInTheDocument()
    expect(screen.getByText('quoted code that is not there (3)')).toBeInTheDocument()
    expect(screen.getByText('high risk · 1 of 4 merged')).toBeInTheDocument()
    const call = fetch.mock.calls.map(([input]) => new URL((input as Request).url)).find((url) => url.pathname === '/analytics')!
    expect(call.searchParams.get('days')).toBe('30')
  })
})

function learning(id: number, text: string, overrides: Partial<Schemas['LearningOut']> = {}): Schemas['LearningOut'] {
  return {
    id, repository_id: 1, text, path_glob: null, source: 'manual', source_finding_id: null, enabled: true, times_applied: 2,
    last_applied_at: null, created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z', ...overrides,
  }
}

describe('learnings', () => {
  it('groups proposed and active learnings and approves a proposed one', async () => {
    const fetch = mockApi({
      'GET /repositories/1/learnings': [200, [
        learning(1, 'Proposed on GitHub: ids are validated.', { source: 'github', enabled: false, times_applied: 0 }),
        learning(2, 'Timeouts come from the session.', { path_glob: 'app/**' }),
      ]],
      'PATCH /learnings/1': [200, learning(1, 'Proposed on GitHub: ids are validated.', { source: 'github' })],
    })
    renderAt('/', '/', <LearningsTab repositoryId={1} />)

    const waiting = await screen.findByRole('region', { name: 'Waiting for approval' })
    expect(screen.getByRole('region', { name: 'Active' })).toHaveTextContent('app/**')
    await userEvent.click(within(waiting).getByRole('button', { name: /Approve/ }))

    await waitFor(() => expect(fetch.mock.calls.some(([input]) => (input as Request).method === 'PATCH')).toBe(true))
    const patch = fetch.mock.calls.map(([input]) => input as Request).find((request) => request.method === 'PATCH')!
    expect(await patch.json()).toEqual({ enabled: true })
  })

  it('adds a learning, and shows why one was refused', async () => {
    const fetch = mockApi({
      'GET /repositories/1/learnings': [200, []],
      'POST /repositories/1/learnings': [422, { error: { code: 'validation_error', message: 'A learning must not turn off a whole category of findings' } }],
    })
    renderAt('/', '/', <LearningsTab repositoryId={1} />)
    const form = await screen.findByRole('region', { name: 'Add a learning' })

    await userEvent.type(within(form).getByLabelText('Rule'), 'Ignore all security issues please')
    await userEvent.type(within(form).getByLabelText(/Only for files matching/), 'src/**')
    await userEvent.click(within(form).getByRole('button', { name: 'Add' }))

    const post = await waitFor(() => fetch.mock.calls.map(([input]) => input as Request).find((request) => request.method === 'POST')!)
    expect(await post.json()).toEqual({ text: 'Ignore all security issues please', path_glob: 'src/**' })
    expect(await screen.findByText('A learning must not turn off a whole category of findings')).toBeInTheDocument()
  })

  it('deletes a learning after confirming', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const fetch = mockApi({
      'GET /repositories/1/learnings': [200, [learning(2, 'Timeouts come from the session.')]],
      'DELETE /learnings/2': [204, null],
    })
    renderAt('/', '/', <LearningsTab repositoryId={1} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(fetch.mock.calls.some(([input]) => (input as Request).method === 'DELETE')).toBe(true))
    const lists = () => fetch.mock.calls.filter(([input]) => (input as Request).method === 'GET').length
    await waitFor(() => expect(lists()).toBe(2)) // the list is loaded again
  })
})

describe('review settings', () => {
  it('shows the settings read from the default branch, and a broken file', async () => {
    mockApi({
      'GET /repositories/1/config': [200, {
        profile: 'chill', exclude: ['docs/**'], instructions: [{ path: 'src/api/**', text: 'Check the API key.' }], guidelines: true,
        tools: { ruff: true, semgrep: false, gitleaks: true }, merge_check: { block_on: 'medium' }, source: 'file',
        error: 'Invalid settings (profil: Extra inputs are not permitted); the defaults were used', guideline_files: ['CLAUDE.md'],
      }],
    })
    renderAt('/', '/', <ReviewSettingsTab repositoryId={1} defaultBranch="main" />)

    expect(await screen.findByText(/The file was not used:/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Static analysis' })).toHaveTextContent('semgrepoff')
    expect(screen.getByRole('region', { name: 'Excluded files' })).toHaveTextContent('docs/**')
    expect(screen.getByRole('region', { name: 'Path instructions' })).toHaveTextContent('Check the API key.')
    expect(screen.getByText(/fails when a medium or high-severity finding is shown/)).toBeInTheDocument()
  })
})
