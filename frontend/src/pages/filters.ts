import type { PullRequestFilters } from '../api/hooks'

/** Filters live in the URL (?status=closed&is_bot=false), so a filtered list can be shared and reloaded. */
export function filtersFromParams(params: URLSearchParams): PullRequestFilters {
  const flag = (name: string) => (params.has(name) ? params.get(name) === 'true' : undefined)
  const status = params.get('status')
  return {
    status: status === 'open' || status === 'closed' ? status : undefined,
    merged: flag('merged'),
    is_bot: flag('is_bot'),
    author: params.get('author') || undefined,
    created_after: params.get('created_after') || undefined,
    created_before: params.get('created_before') || undefined,
  }
}
