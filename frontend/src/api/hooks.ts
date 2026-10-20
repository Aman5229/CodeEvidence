import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, type Schemas, unwrap } from './client'

// One hook per endpoint. TanStack Query caches each answer by its key, refetches when a page
// is opened again, and shares one request between components asking for the same data.

export type PullRequestFilters = {
  status?: 'open' | 'closed'
  merged?: boolean
  author?: string
  is_bot?: boolean
  created_after?: string
  created_before?: string
}

export function useRepositories() {
  return useQuery({
    queryKey: ['repositories'],
    queryFn: async () => unwrap(await api.GET('/repositories', { params: { query: { limit: 100 } } })),
  })
}

export function useRepository(id: number) {
  return useQuery({
    queryKey: ['repository', id],
    queryFn: async () =>
      unwrap(await api.GET('/repositories/{repository_id}', { params: { path: { repository_id: id } } })),
  })
}

export function useRepositoryStats(id: number) {
  return useQuery({
    queryKey: ['repository-stats', id],
    queryFn: async () =>
      unwrap(await api.GET('/repositories/{repository_id}/stats', { params: { path: { repository_id: id } } })),
  })
}

export function usePullRequests(repositoryId: number, filters: PullRequestFilters) {
  return useInfiniteQuery({
    queryKey: ['pull-requests', repositoryId, filters],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET('/repositories/{repository_id}/pull-requests', {
          params: { path: { repository_id: repositoryId }, query: { ...filters, limit: 20, cursor: pageParam } },
        }),
      ),
    // The API's cursor paging: send next_cursor back to get the next page; null on the last one
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  })
}

export function usePullRequest(id: number) {
  return useQuery({
    queryKey: ['pull-request', id],
    queryFn: async () =>
      unwrap(
        await api.GET('/pull-requests/{pull_request_id}', {
          params: { path: { pull_request_id: id }, query: { include_patch: true } },
        }),
      ),
  })
}

export function useOverview() {
  return useQuery({
    queryKey: ['overview'],
    queryFn: async () => unwrap(await api.GET('/overview')),
  })
}

/** Risk and latest-review status for the PRs on screen, in one request. */
export function useInsights(ids: number[]) {
  return useQuery({
    queryKey: ['insights', ids],
    enabled: ids.length > 0,
    queryFn: async () =>
      unwrap(await api.GET('/pull-requests/insights', { params: { query: { ids: ids.slice(0, 100) } } })),
  })
}

export function useIndexStatus(repositoryId: number) {
  return useQuery({
    queryKey: ['index', repositoryId],
    queryFn: async () =>
      unwrap(
        await api.GET('/repositories/{repository_id}/index', { params: { path: { repository_id: repositoryId } } }),
      ),
  })
}

export function useQueueIndex(repositoryId: number) {
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST('/repositories/{repository_id}/index', { params: { path: { repository_id: repositoryId } } }),
      ),
  })
}

/** The PR's review runs, newest first. While a queued review is awaited (`waitingBeyond` =
 * the run count when it was queued), refetch every 3 s until a new run appears. */
export function useReviewRuns(pullRequestId: number, waitingBeyond: number | null = null) {
  return useQuery({
    queryKey: ['review-runs', pullRequestId],
    refetchInterval: (query) =>
      waitingBeyond !== null && (query.state.data?.length ?? 0) <= waitingBeyond ? 3000 : false,
    queryFn: async () =>
      unwrap(
        await api.GET('/pull-requests/{pull_request_id}/reviews', {
          params: { path: { pull_request_id: pullRequestId } },
        }),
      ),
  })
}

export type JobStatus = 'queued' | 'running' | 'retrying' | 'succeeded' | 'failed'

export function useJobs(status: JobStatus) {
  return useQuery({
    queryKey: ['jobs', status],
    queryFn: async () => unwrap(await api.GET('/jobs', { params: { query: { status, limit: 50 } } })),
  })
}

export function useRetryJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (jobId: number) =>
      unwrap(await api.POST('/jobs/{job_id}/retry', { params: { path: { job_id: jobId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

/** Readiness of the API's dependencies. A 503 still carries the per-dependency checks. */
export function useReadiness() {
  return useQuery({
    queryKey: ['readiness'],
    refetchInterval: 30_000,
    queryFn: async () => {
      const result = await api.GET('/health/ready')
      return { ok: result.response.ok, checks: (result.data ?? result.error) as { checks?: Record<string, string> } | undefined }
    },
  })
}

/** 404 means "not computed yet": shown as empty, not as an error. */
async function orNull<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load()
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export function useRisk(id: number) {
  return useQuery({
    queryKey: ['risk', id],
    queryFn: () =>
      orNull(async () =>
        unwrap(await api.GET('/pull-requests/{pull_request_id}/risk', { params: { path: { pull_request_id: id } } })),
      ),
  })
}

export function useReview(id: number) {
  return useQuery({
    queryKey: ['review', id],
    queryFn: () =>
      orNull(async () =>
        unwrap(await api.GET('/pull-requests/{pull_request_id}/review', { params: { path: { pull_request_id: id } } })),
      ),
  })
}

/** auto: only the files changed since the last review when the PR got new commits on top of
 * it (incremental); full: everything. */
export type ReviewMode = 'auto' | 'full'

export function useQueueReview(id: number) {
  return useMutation({
    mutationFn: async (mode: ReviewMode = 'auto') =>
      unwrap(
        await api.POST('/pull-requests/{pull_request_id}/review', {
          params: { path: { pull_request_id: id }, query: { mode } },
        }),
      ),
  })
}

type Verdict = 'useful' | 'not_useful'

/** Rate a finding. Optimistic: the count changes at once, and is rolled back if saving fails.
 * A reason given with "not useful" becomes a learning for future reviews. */
export function useFeedback(pullRequestId: number) {
  const queryClient = useQueryClient()
  const key = ['review', pullRequestId]
  return useMutation({
    mutationFn: async ({ findingId, verdict, reason }: { findingId: number; verdict: Verdict; reason?: string }) =>
      unwrap(
        await api.POST('/findings/{finding_id}/feedback', {
          params: { path: { finding_id: findingId } },
          body: reason ? { verdict, reason } : { verdict },
        }),
      ),
    onMutate: async ({ findingId, verdict }) => {
      await queryClient.cancelQueries({ queryKey: key })
      const before = queryClient.getQueryData<Schemas['ReviewOut'] | null>(key)
      if (before) {
        queryClient.setQueryData<Schemas['ReviewOut']>(key, {
          ...before,
          findings: before.findings.map((finding) =>
            finding.id === findingId
              ? { ...finding, feedback: { ...finding.feedback, [verdict]: finding.feedback[verdict] + 1 } }
              : finding,
          ),
        })
      }
      return { before }
    },
    onError: (_error, _vars, context) => queryClient.setQueryData(key, context?.before),
    onSettled: () => queryClient.invalidateQueries({ queryKey: key }),
  })
}

// ---------- the new review features ----------

/** A 204 (nothing to return) is fine; any other answer without data is an error. */
function ensureOk(result: { error?: unknown; response: Response }): void {
  if (!result.response.ok) unwrap({ ...result, data: undefined })
}

export function useImpact(id: number) {
  return useQuery({
    queryKey: ['impact', id],
    queryFn: async () =>
      unwrap(await api.GET('/pull-requests/{pull_request_id}/impact', { params: { path: { pull_request_id: id } } })),
  })
}

export function useChatHistory(pullRequestId: number) {
  return useQuery({
    queryKey: ['chat', pullRequestId],
    queryFn: async () =>
      unwrap(
        await api.GET('/pull-requests/{pull_request_id}/chat', { params: { path: { pull_request_id: pullRequestId } } }),
      ),
  })
}

export function useLearnings(repositoryId: number) {
  return useQuery({
    queryKey: ['learnings', repositoryId],
    queryFn: async () =>
      unwrap(
        await api.GET('/repositories/{repository_id}/learnings', { params: { path: { repository_id: repositoryId } } }),
      ),
  })
}

export function useAddLearning(repositoryId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: { text: string; path_glob: string | null }) =>
      unwrap(
        await api.POST('/repositories/{repository_id}/learnings', {
          params: { path: { repository_id: repositoryId } },
          body,
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['learnings', repositoryId] }),
  })
}

export type LearningChange = { text?: string; path_glob?: string | null; enabled?: boolean }

export function useChangeLearning(repositoryId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, change }: { id: number; change: LearningChange }) =>
      unwrap(await api.PATCH('/learnings/{learning_id}', { params: { path: { learning_id: id } }, body: change })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['learnings', repositoryId] }),
  })
}

export function useDeleteLearning(repositoryId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) =>
      ensureOk(await api.DELETE('/learnings/{learning_id}', { params: { path: { learning_id: id } } })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['learnings', repositoryId] }),
  })
}

export function useRepositoryConfig(repositoryId: number) {
  return useQuery({
    queryKey: ['repository-config', repositoryId],
    queryFn: async () =>
      unwrap(
        await api.GET('/repositories/{repository_id}/config', { params: { path: { repository_id: repositoryId } } }),
      ),
  })
}

export function useReviewQueue(repositoryId: number | null) {
  return useQuery({
    queryKey: ['review-queue', repositoryId],
    queryFn: async () =>
      unwrap(
        await api.GET('/review-queue', {
          params: { query: repositoryId == null ? { limit: 100 } : { repository_id: repositoryId, limit: 100 } },
        }),
      ),
  })
}

export function useAnalytics(days: number, repositoryId: number | null) {
  return useQuery({
    queryKey: ['analytics', days, repositoryId],
    queryFn: async () =>
      unwrap(
        await api.GET('/analytics', {
          params: { query: repositoryId == null ? { days } : { days, repository_id: repositoryId } },
        }),
      ),
  })
}
