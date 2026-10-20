import type { Schemas } from '../api/client'

export const FINDING: Schemas['FindingOut'] = {
  id: 11, rank: 1, path: 'app/handler.py', line: 3, severity: 'high', category: 'security',
  claim: 'eval runs request data as code.', quote: 'return eval(item_id)', suggestion: 'Use int(item_id).',
  confidence: 0.9, github_comment_id: null,
  evidence: [{ id: 'H1', kind: 'hunk', path: 'app/handler.py', start_line: 1, end_line: 3, text: '+    return eval(item_id)' }],
  feedback: { useful: 2, not_useful: 0, replies: 0 },
}

export const REVIEW: Schemas['ReviewOut'] = {
  id: 1, pull_request_id: 7, head_sha: 'b'.repeat(40), status: 'completed', summary: 'Evaluates the request id.',
  findings: [FINDING, { ...FINDING, id: 12, severity: 'low', category: 'maintainability', line: 2, claim: 'Name is unclear here.', quote: 'item_id = request.args["id"]' }],
  dropped_findings: 1,
  evidence: [
    ...FINDING.evidence,
    { id: 'S1', kind: 'signal', path: 'app/handler.py', start_line: 3, end_line: 3, text: 'dynamic_code_execution' },
    { id: 'R1', kind: 'related', path: 'app/utils.py', start_line: 10, end_line: 20, text: 'def load(id): ...' },
  ],
  prompt_version: 'review_v1', model: 'qwen2.5-coder:7b', cached: false, llm_calls: 2, input_tokens: 3263,
  output_tokens: 241, cost_usd: 0, latency_ms: 18602, published_at: null, created_at: '2026-10-19T10:00:00Z',
}

export const PULL_REQUEST: Schemas['PullRequestDetailWithPatch'] = {
  id: 7, repository_id: 1, number: 42, title: 'Parse the id', author_login: 'alice', status: 'open',
  created_at: '2026-10-18T10:00:00Z', closed_at: null, merged_at: null, body: null, base_branch: 'main',
  head_branch: 'parse-id', head_sha: 'b'.repeat(40), updated_at: '2026-10-18T10:00:00Z', is_bot: false, is_merged: false,
  totals: { files_changed: 2, additions: 3, deletions: 1, lines_changed: 4 },
  files: [
    { path: 'app/handler.py', previous_path: null, status: 'modified', additions: 2, deletions: 1, changes: 3,
      patch: '@@ -1,2 +1,3 @@\n def handler(request):\n-    return load(request.args["id"])\n+    item_id = request.args["id"]\n+    return eval(item_id)' },
    { path: 'docs/notes.md', previous_path: null, status: 'added', additions: 1, deletions: 0, changes: 1, patch: '@@ -0,0 +1 @@\n+notes' },
  ],
}
