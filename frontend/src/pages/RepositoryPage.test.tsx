import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { mockApi, renderAt } from '../test/render'
import { filtersFromParams } from './filters'
import { RepositoryPage } from './RepositoryPage'

const pr = (id: number) => ({
  id, repository_id: 1, number: id, title: `PR ${id}`, author_login: 'alice', status: 'closed', created_at: '2026-10-01T10:00:00Z',
  closed_at: null, merged_at: null, is_bot: false, is_merged: false,
})

describe('filtersFromParams', () => {
  it('reads filters from the URL and ignores bad values', () => {
    expect(filtersFromParams(new URLSearchParams('status=closed&is_bot=false&merged=true&status2=x'))).toEqual({
      status: 'closed', merged: true, is_bot: false, author: undefined, created_after: undefined, created_before: undefined,
    })
    expect(filtersFromParams(new URLSearchParams('status=weird')).status).toBeUndefined()
  })
})

describe('RepositoryPage', () => {
  it('sends the URL filters to the API and loads more with the cursor', async () => {
    const fetch = mockApi({
      'GET /repositories/1': [200, { id: 1, full_name: 'octo/demo', owner: 'octo', default_branch: 'main', html_url: '', is_private: false, last_synced_at: '2026-10-01T10:00:00Z' }],
      'GET /repositories/1/stats': [500, { error: { code: 'internal_error', message: 'boom' } }],
      'GET /repositories/1/pull-requests': [200, { items: [pr(1)], next_cursor: 'abc' }],
    })

    renderAt('/repositories/1?status=closed&is_bot=false', '/repositories/:repositoryId', <RepositoryPage />)

    expect(await screen.findByText('PR 1')).toBeInTheDocument()
    const listCall = () => fetch.mock.calls.map(([input]) => new URL((input as Request).url)).filter((u) => u.pathname.endsWith('pull-requests'))
    expect(listCall()[0].searchParams.get('status')).toBe('closed')
    expect(listCall()[0].searchParams.get('is_bot')).toBe('false')

    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(listCall()[1].searchParams.get('cursor')).toBe('abc')
  })

  it('explains a missing API key', async () => {
    const unauthorized: [number, unknown] = [401, { error: { code: 'unauthorized', message: 'Missing API key' } }]
    mockApi({
      'GET /repositories/1': unauthorized,
      'GET /repositories/1/stats': unauthorized,
      'GET /repositories/1/pull-requests': unauthorized,
    })

    renderAt('/repositories/1', '/repositories/:repositoryId', <RepositoryPage />)

    expect(await screen.findByText(/Missing API key/)).toBeInTheDocument()
    expect(screen.getByText(/Add your API key in Settings/)).toBeInTheDocument()
  })
})
