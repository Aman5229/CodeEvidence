import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { parseEvents } from '../../api/chat'
import type { Schemas } from '../../api/client'
import { FINDING, PULL_REQUEST, REVIEW } from '../../test/fixtures'
import { eventStream, mockApi, renderAt, renderWithClient } from '../../test/render'
import { ChatPanel } from '../chat/ChatPanel'
import { Markdown } from '../chat/Markdown'
import { EvidenceTab } from './EvidenceTab'
import { FindingCard } from './FindingCard'
import { ImpactTab } from './ImpactTab'
import { RunsTab } from './RunsTab'
import { WalkthroughTab } from './WalkthroughTab'

vi.mock('mermaid', () => ({
  default: { initialize: vi.fn(), render: vi.fn(async () => ({ svg: '<svg data-testid="mermaid-svg"></svg>' })) },
}))

describe('one-click fixes', () => {
  it('shows the line and its replacement, and links to the GitHub comment to commit it', () => {
    renderWithClient(
      <FindingCard finding={{ ...FINDING, github_comment_id: 123 }} pullRequestId={7} pullRequestUrl="https://github.com/octo/demo/pull/42" />,
    )

    const change = screen.getByRole('table', { name: 'Suggested change' })
    const [removed, added] = within(change).getAllByRole('row')
    expect(removed).toHaveTextContent('return eval(item_id)')
    expect(added).toHaveTextContent('return int(item_id)')
    expect(screen.getByRole('link', { name: /Commit on GitHub/ })).toHaveAttribute('href', 'https://github.com/octo/demo/pull/42#discussion_r123')
  })

  it('copies the fix and the prompt for AI agents', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText')
    renderWithClient(<FindingCard finding={FINDING} pullRequestId={7} />)

    await user.click(screen.getByRole('button', { name: 'Copy fix' }))
    await user.click(screen.getByRole('button', { name: 'Copy prompt' }))

    expect(writeText.mock.calls).toEqual([['    return int(item_id)'], ['In `app/handler.py` at line 3: eval runs request data as code.']])
    expect(screen.queryByRole('link', { name: /Commit on GitHub/ })).not.toBeInTheDocument() // not posted yet
  })

  it('has no fix section when the reviewer could not write one', () => {
    renderWithClient(<FindingCard finding={{ ...FINDING, replacement: null, original_line: null }} pullRequestId={7} />)

    expect(screen.queryByRole('table', { name: 'Suggested change' })).not.toBeInTheDocument()
  })

  it('marks findings carried over from an earlier review', () => {
    renderWithClient(<FindingCard finding={{ ...FINDING, carried_from_review_id: 4 }} pullRequestId={7} />)

    expect(screen.getByText('from review #4')).toBeInTheDocument()
  })
})

describe('a 👎 with a reason', () => {
  it('sends the reason, which becomes a learning', async () => {
    const fetch = mockApi({
      'POST /findings/11/feedback': [201, { id: 1, finding_id: 11, verdict: 'not_useful', created_at: '2026-10-19T10:00:00Z', learning_job_id: 9 }],
    })
    renderWithClient(<FindingCard finding={FINDING} pullRequestId={7} />)

    await userEvent.click(screen.getByRole('button', { name: 'Not useful' }))
    await userEvent.type(screen.getByLabelText(/Why is it not useful/), 'ids are validated by middleware')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    expect(await (fetch.mock.calls[0][0] as Request).json()).toEqual({ verdict: 'not_useful', reason: 'ids are validated by middleware' })
  })

  it('can be sent without a reason', async () => {
    const fetch = mockApi({
      'POST /findings/11/feedback': [201, { id: 1, finding_id: 11, verdict: 'not_useful', created_at: '2026-10-19T10:00:00Z', learning_job_id: null }],
    })
    renderWithClient(<FindingCard finding={FINDING} pullRequestId={7} />)

    await userEvent.click(screen.getByRole('button', { name: 'Not useful' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    expect(await (fetch.mock.calls[0][0] as Request).json()).toEqual({ verdict: 'not_useful' })
  })
})

describe('walkthrough', () => {
  const review: Schemas['ReviewOut'] = {
    ...REVIEW,
    mode: 'incremental',
    compared_from_sha: 'c'.repeat(40),
    effort: { level: 2, minutes: 15 },
    diagram: 'sequenceDiagram\n    Client->>handler: request',
    check_state: 'failure',
    published_at: '2026-10-19T10:00:00Z',
    tools: [
      { name: 'ruff', ran: true, findings: 2, error: null, duration_ms: 12 },
      { name: 'gitleaks', ran: false, findings: 0, error: 'not installed', duration_ms: 0 },
    ],
    config: {
      profile: 'assertive', exclude: [], instructions: [], guidelines: true, tools: { ruff: true, semgrep: true, gitleaks: true },
      merge_check: { block_on: 'high' }, source: 'file', error: null, guideline_files: ['CLAUDE.md'],
    },
  }

  it('shows the effort, the incremental scope, the diagram and the checks', async () => {
    renderAt('/', '/', <WalkthroughTab pullRequest={PULL_REQUEST} review={review} risk={null} onOpenFile={() => {}} onRunReview={() => {}} />)

    expect(screen.getByText(/Review effort 2\/5 · ~15 min/)).toBeInTheDocument()
    expect(screen.getByText(/incremental since ccccccc/)).toBeInTheDocument()
    expect(await screen.findByTestId('mermaid-svg')).toBeInTheDocument()
    const checks = screen.getByRole('region', { name: 'Checks and settings' })
    expect(checks).toHaveTextContent('blocking')
    expect(checks).toHaveTextContent('ruff · 2')
    expect(checks).toHaveTextContent('gitleaks · skipped')
    expect(checks).toHaveTextContent('assertive')
    expect(checks).toHaveTextContent('CLAUDE.md')
  })
})

describe('evidence and runs', () => {
  it('shows learnings, instructions and carried evidence', () => {
    renderWithClient(
      <EvidenceTab
        review={{
          ...REVIEW,
          evidence: [
            ...REVIEW.evidence,
            { id: 'L1', kind: 'learning', path: 'app/**', start_line: null, end_line: null, text: 'Ids are validated by middleware.', source_id: 3 },
            { id: 'P1', kind: 'instruction', path: 'app/**', start_line: null, end_line: null, text: 'Never use eval.' },
            { id: 'C1', kind: 'hunk', path: 'app/old.py', start_line: 1, end_line: 2, text: '+x = 1' },
          ],
        }}
      />,
    )

    expect(screen.getByRole('region', { name: 'Learnings' })).toHaveTextContent('L1')
    expect(screen.getByRole('region', { name: 'Path instructions' })).toHaveTextContent('P1')
    expect(screen.getByRole('region', { name: 'Diff hunks' })).toHaveTextContent('earlier review')
  })

  it('marks incremental runs and their merge check', () => {
    const run: Schemas['ReviewRunOut'] = {
      id: 5, status: 'completed', mode: 'incremental', base_review_id: 4, model: 'm', prompt_version: 'review_v2', cached: false,
      llm_calls: 3, input_tokens: 10, output_tokens: 5, cost_usd: 0, latency_ms: 10, findings_shown: 1, findings_dropped: 0,
      check_state: 'success', published_at: null, created_at: '2026-10-19T10:00:00Z',
    }
    renderWithClient(<RunsTab runs={[run]} loading={false} />)

    expect(screen.getByText('incremental')).toHaveAttribute('title', 'Builds on review #4')
    expect(screen.getByText('check success')).toBeInTheDocument()
  })
})

describe('impact', () => {
  const impact: Schemas['ImpactOut'] = {
    pull_request_id: 7,
    indexed: true,
    truncated: false,
    changed: [
      { path: 'app/invoices.py', status: 'modified', additions: 2, deletions: 1, symbols: [{ name: 'load_invoice', kind: 'function', change: 'modified' }] },
      { path: 'app/payments.py', status: 'added', additions: 2, deletions: 0, symbols: [{ name: 'refund_payment', kind: 'function', change: 'added' }] },
    ],
    dependents: [
      { path: 'app/routes.py', is_test: false, uses: ['load_invoice'], changed_files: ['app/invoices.py'], chunks: [{ name: 'show_invoice', kind: 'function', start_line: 1, end_line: 3, uses: ['load_invoice'] }] },
      { path: 'tests/test_invoices.py', is_test: true, uses: ['load_invoice'], changed_files: ['app/invoices.py'], chunks: [{ name: 'test_load_invoice', kind: 'function', start_line: 1, end_line: 2, uses: ['load_invoice'] }] },
    ],
  }

  it('draws changed files and their users, and opens a changed file on click', async () => {
    mockApi({ 'GET /pull-requests/7/impact': [200, impact] })
    const opened: string[] = []
    renderAt('/', '/', <ImpactTab pullRequestId={7} repositoryId={1} onOpenFile={(path) => opened.push(path)} />)

    const node = await screen.findByRole('button', { name: 'app/invoices.py: 1 changed symbols' })
    expect(screen.getByRole('button', { name: 'tests/test_invoices.py uses load_invoice' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Used by' })).toHaveTextContent('show_invoice (1-3)')
    expect(screen.getByRole('region', { name: 'Changed code' })).toHaveTextContent('refund_payment')

    await userEvent.click(node)
    expect(opened).toEqual(['app/invoices.py'])
  })

  it('explains what is missing without a code index', async () => {
    mockApi({ 'GET /pull-requests/7/impact': [200, { ...impact, indexed: false, dependents: [] }] })
    renderAt('/', '/', <ImpactTab pullRequestId={7} repositoryId={1} onOpenFile={() => {}} />)

    expect(await screen.findByRole('link', { name: 'Index the code' })).toHaveAttribute('href', '/repositories/1?tab=index')
  })
})

describe('chat', () => {
  it('splits server-sent events and keeps an unfinished one for later', () => {
    const { events, rest } = parseEvents('event: token\ndata: {"text":"Hi"}\n\n: ping\n\nevent: token\ndata: {"te')

    expect(events).toEqual([{ event: 'token', data: '{"text":"Hi"}' }])
    expect(rest).toBe('event: token\ndata: {"te')
  })

  it('renders Markdown safely with citations, and hides citations the model made up', async () => {
    const cited: string[] = []
    renderWithClient(
      <Markdown text={'It uses **eval** [H1] [Z9]:\n\n- `item_id` <img src=x>\n\n```\nreturn eval(item_id)\n```'} known={new Set(['H1'])} onCite={(id) => cited.push(id)} />,
    )

    expect(screen.getByText('eval', { selector: 'strong' })).toBeInTheDocument()
    expect(screen.getByText('item_id', { selector: 'code' })).toBeInTheDocument()
    expect(screen.getByText(/<img src=x>/)).toBeInTheDocument() // shown as text, never as HTML
    expect(screen.queryByRole('button', { name: 'Evidence Z9' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Evidence H1' }))
    expect(cited).toEqual(['H1'])
  })

  it('streams an answer, then shows it with its sources', async () => {
    const message = (id: number, role: string, content: string, citations: Schemas['CitationOut'][] = []) => ({
      id, role, content, citations, source: 'dashboard', github_user: null, model: role === 'user' ? null : 'qwen', cost_usd: role === 'user' ? null : 0,
      latency_ms: role === 'user' ? null : 900, created_at: '2026-10-19T10:00:00Z',
    })
    const answer = 'It runs eval on the id [H1].'
    const fetch = mockApi({
      'GET /pull-requests/7/chat': [200, []],
      'POST /pull-requests/7/chat': () =>
        eventStream([
          ['token', { text: 'It runs eval ' }],
          ['token', { text: 'on the id [H1].' }],
          ['done', {
            question: message(1, 'user', 'Is it safe?'),
            answer: message(2, 'assistant', answer, [{ id: 'H1', kind: 'hunk', path: 'app/handler.py', start_line: 1, end_line: 3 }]),
            unknown_citations: [],
          }],
        ]),
    })
    const opened: string[] = []
    renderAt('/', '/', <ChatPanel pullRequestId={7} onOpenFile={(path) => opened.push(path)} />)

    await userEvent.click(screen.getByRole('button', { name: /Ask CodeEvidence/ }))
    await userEvent.type(screen.getByLabelText('Your question'), 'Is it safe?{Enter}')

    const source = await screen.findByRole('button', { name: /app\/handler.py:1-3/ })
    const post = fetch.mock.calls.map(([input, init]) => (input instanceof Request ? input : new Request(input, init))).find((request) => request.method === 'POST')!
    expect(await post.json()).toEqual({ question: 'Is it safe?' })
    expect(screen.getByRole('dialog', { name: 'Ask CodeEvidence' })).toHaveTextContent('It runs eval on the id')
    await userEvent.click(source)
    expect(opened).toEqual(['app/handler.py'])
  })

  it('shows the error when there is no answer', async () => {
    mockApi({
      'GET /pull-requests/7/chat': [200, []],
      'POST /pull-requests/7/chat': () => eventStream([['error', { message: 'Answering would go over the budget for one answer.' }]]),
    })
    renderAt('/', '/', <ChatPanel pullRequestId={7} onOpenFile={() => {}} />)

    await userEvent.click(screen.getByRole('button', { name: /Ask CodeEvidence/ }))
    await userEvent.click(screen.getByRole('button', { name: 'What does this change do?' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('over the budget')
  })
})
