import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { FINDING, PULL_REQUEST, REVIEW } from '../../test/fixtures'
import { mockApi, renderAt, renderWithClient } from '../../test/render'
import { ChangeMap } from './ChangeMap'
import { EvidenceTab } from './EvidenceTab'
import { FilesTab } from './FilesTab'
import { FindingCard } from './FindingCard'
import { FindingsTab } from './FindingsTab'
import { ReviewProgress } from './ReviewProgress'
import { RiskTab } from './RiskTab'

describe('FindingCard', () => {
  it('shows the claim, the quoted code, the fix and the evidence', () => {
    renderWithClient(<FindingCard finding={FINDING} pullRequestId={7} />)

    expect(screen.getByText('eval runs request data as code.')).toBeInTheDocument()
    expect(screen.getByText('app/handler.py:3')).toBeInTheDocument()
    expect(screen.getByText('Use int(item_id).')).toBeInTheDocument()
    expect(screen.getByText(/Evidence: H1/)).toBeInTheDocument()
  })

  it('saves feedback with the API key', async () => {
    localStorage.setItem('codeevidence.apiKey', 'ce_test')
    const fetch = mockApi({ 'POST /findings/11/feedback': [201, { id: 1, finding_id: 11, verdict: 'useful', created_at: '2026-10-19T10:00:00Z' }] })

    renderWithClient(<FindingCard finding={FINDING} pullRequestId={7} />)
    await userEvent.click(screen.getByRole('button', { name: 'Useful' }))

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    const request = fetch.mock.calls[0][0] as Request
    expect(request.headers.get('X-API-Key')).toBe('ce_test')
    expect(await request.json()).toEqual({ verdict: 'useful' })
  })
})

describe('FilesTab', () => {
  it('shows each finding right under the line it is about', () => {
    renderWithClient(<FilesTab pullRequest={PULL_REQUEST} findings={[FINDING]} focusPath={null} />)

    const diff = screen.getByRole('table', { name: 'Diff of app/handler.py' })
    const rows = within(diff).getAllByRole('row')
    const flagged = rows.find((row) => row.classList.contains('flagged'))
    expect(flagged).toHaveTextContent('return eval(item_id)')
    expect(flagged?.nextElementSibling).toHaveTextContent('eval runs request data as code.')
  })

  it('can hide files without findings', async () => {
    renderWithClient(<FilesTab pullRequest={PULL_REQUEST} findings={[FINDING]} focusPath={null} />)
    expect(screen.getByRole('table', { name: 'Diff of docs/notes.md' })).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText(/Only files with findings/))

    expect(screen.queryByRole('table', { name: 'Diff of docs/notes.md' })).not.toBeInTheDocument()
  })
})

describe('FindingsTab', () => {
  it('filters by severity and says how many were dropped', async () => {
    renderWithClient(<FindingsTab review={REVIEW} pullRequestId={7} onShowInDiff={() => {}} />)
    expect(screen.getAllByRole('article')).toHaveLength(2)
    expect(screen.getByText(/1 more finding was proposed/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /low 1/ }))

    expect(screen.getAllByRole('article')).toHaveLength(1)
    expect(screen.getByText('Name is unclear here.')).toBeInTheDocument()
  })
})

describe('EvidenceTab', () => {
  it('groups evidence by kind and shows what was cited', () => {
    renderWithClient(<EvidenceTab review={REVIEW} />)

    expect(screen.getByRole('region', { name: 'Rule signals' })).toHaveTextContent('S1')
    expect(screen.getByRole('region', { name: 'Related code' })).toHaveTextContent('not cited')
    expect(screen.getByRole('region', { name: 'Diff hunks' })).toHaveTextContent('cited by 2')
  })
})

describe('RiskTab', () => {
  it('shows the score, every reason and that no model is loaded', () => {
    renderWithClient(
      <RiskTab
        risk={{
          pull_request_id: 7, score: 55, level: 'medium', version: 'rules-v1', computed_at: '2026-10-19T10:00:00Z', model: null,
          reasons: [{ code: 'no_tests', message: 'No test files changed', points: 20 }],
          features: { files_changed: 4, lines_changed: 300, log_lines_changed: 5.7, test_file_ratio: 0, docs_only: false, is_bot: false, size_percentile: 0.8 },
        }}
      />,
    )

    expect(screen.getByRole('img', { name: /Risk score 55 of 100, medium/ })).toBeInTheDocument()
    expect(screen.getByText('No test files changed')).toBeInTheDocument()
    expect(screen.getByText('+20')).toBeInTheDocument()
    expect(screen.getByText(/only the rule score applies/)).toBeInTheDocument()
  })
})

describe('motion details', () => {
  it('expands a finding’s evidence on demand', async () => {
    renderWithClient(<FindingCard finding={FINDING} pullRequestId={7} />)
    const toggle = screen.getByRole('button', { name: /Evidence: H1/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('+    return eval(item_id)')).not.toBeInTheDocument()

    await userEvent.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Diff hunk')).toBeInTheDocument()
  })

  it('change map: one block per file, sized by its lines, opening the file on click', async () => {
    const opened: string[] = []
    renderWithClient(<ChangeMap files={PULL_REQUEST.files} findings={[FINDING]} onOpenFile={(path) => opened.push(path)} />)

    const block = screen.getByRole('button', { name: 'app/handler.py: 3 lines changed, findings: high' })
    expect(block).toHaveClass('has-high')
    expect(screen.getByRole('button', { name: 'docs/notes.md: 1 lines changed' })).not.toHaveClass('has-findings')

    await userEvent.click(block)
    expect(opened).toEqual(['app/handler.py'])
  })

  it('review progress shows the real elapsed time', () => {
    renderAt('/', '/', <ReviewProgress since={Date.now() - 83_000} />) // it links to Jobs: needs a router

    expect(screen.getByRole('status')).toHaveTextContent('1:23 elapsed')
  })
})
