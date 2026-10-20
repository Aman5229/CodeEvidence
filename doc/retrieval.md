# Code retrieval (the R in RAG)

A diff alone hides most of what a reviewer needs: the rest of the function, the code that
calls it, similar code elsewhere. This part gives the AI reviewer that context, as an
**evidence bundle** where every item has an id the reviewer must cite.

**Status:** built and tested with a fake embedder (unit tests) and against pgvector
(integration tests, which need Docker). The retrieval numbers in section 6 need a labelled
set; none are measured yet.

## 1. From a PR to evidence

```
PR files (patches) ──> diff parser ──> hunks with line numbers ─┐
                    └> file filters (skip lock, vendored, generated, binary)
file at head SHA ───> tree-sitter chunks ──> the function around each hunk ─┤
repository index ───> hybrid search per hunk ──> related code ─────────────┼──> evidence bundle
added lines ────────> regex rules ──> signals (eval, shell=True, secrets...) ┘    (token budget)
```

| Step | Code | Notes |
|---|---|---|
| Diff parser | `app/modules/code/diff.py` | `@@ -a,b +c,d @@` headers; every line gets its old and new number |
| File filters | `filters.py` | lock files, `vendor/`, `node_modules/`, `*.min.js`, `*_pb2.py`, binaries, files over 200 kB, files that say "generated" in their first lines |
| File contents | `contents.py` | GitHub blobs API, cached by blob SHA in `file_blobs`; the same SHA is always the same text, so the cache never goes stale |
| Chunking | `chunking.py` | tree-sitter for Python and JavaScript: one chunk per function, method or class; definitions over 120 lines and other languages use 60-line windows with 10 lines of overlap |
| Embeddings | `embeddings.py` | `LocalEmbedder` (sentence-transformers, `BAAI/bge-small-en-v1.5`, 384 numbers) or `FakeEmbedder` (hashed words, for tests) |
| Index | `indexing.py`, table `code_chunks` | default branch only; a re-run skips files whose blob SHA and model are unchanged |
| Retrieval | `retrieval.py` | vector + full-text, merged with reciprocal rank fusion |
| Signals | `signals.py` | 9 risky patterns, dependency changes, missing tests |
| Bundle | `evidence.py` | ids H (hunk), F (function), R (related), S (signal); trimmed to 12,000 tokens |

## 2. Why chunk by structure

A search hit should be something a person can read on its own. A function is a complete
thought; 1,000 characters cut at random is half of one function and half of the next. With
tree-sitter, a chunk carries its path, name and line range, so the reviewer can say "see
`Session.refresh` in `auth/session.py`, lines 40-62".

**Limits:** code at module level (constants, route registration) is only indexed when a file
has no definitions at all; TypeScript and other languages use windows until their grammars
are added.

## 3. Embeddings

An embedding turns text into a list of numbers so that similar texts get nearby lists.
"Nearby" is measured with cosine similarity (the angle between two vectors).

- **Local model** (`BAAI/bge-small-en-v1.5`): free, private (code never leaves the machine),
  384 numbers per chunk, runs on CPU. A general-text model, not a code model: section 6
  measures whether that is good enough. A code model (e.g. `jina-embeddings-v2-base-code`)
  is the first thing to try if it is not; changing the model re-embeds everything (the
  model name is stored per chunk).
- **Fake embedder:** hashes each word into one of 384 positions. Deterministic and instant,
  and texts that share words still end up close, so retrieval tests are meaningful in CI.
- The text embedded is `path + name + code`, so where the code lives counts too.

## 4. pgvector

`code_chunks.embedding` is a `vector(384)` column with an **HNSW** index using cosine
distance. HNSW is an approximate nearest-neighbour graph: much faster than comparing with
every row, and it may very rarely miss the true nearest neighbour. Alternative: IVFFlat,
which needs training on existing data and gets worse as rows are added without a rebuild.
At this project's size (thousands to tens of thousands of chunks) even an exact scan is
fast; the index is there for the pattern.

## 5. Hybrid retrieval

- **Vector search** finds code that means something similar, even with different names.
- **Keyword search** (Postgres full-text, `ts_rank_cd`) finds code that uses the same names.
  Identifiers are split first (`getUserById` becomes `get user by id`) on both sides, so
  `user` matches either style.
- **Reciprocal rank fusion:** each chunk scores `sum of 1 / (60 + rank)` over both lists.
  Ranks, not raw scores, so a cosine distance and a text rank never need to be made
  comparable, and there is nothing to tune.

For each hunk (at most 30 per PR), the 3 best related chunks are kept, leaving out the
changed code itself.

## 6. Evaluation: recall@k and MRR

```bash
python -m scripts.eval_retrieval sample --count 30   # writes eval/retrieval_gold.jsonl
# label: for each hunk, the code a reviewer would want to see
python -m scripts.eval_retrieval report              # vector vs keyword vs hybrid
```

- **Recall@k:** the share of the relevant chunks found in the top k.
- **MRR** (mean reciprocal rank): 1 / the position of the first relevant chunk, averaged.
  1.0 means the first result is always relevant.

| Mode | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|
| vector | *pending* | | | | |
| keyword | *pending* | | | | |
| hybrid | *pending* | | | | |

The setting with the best recall@5 is kept (hybrid is the default until measured). The
labelled set is small and labelled by one person, so differences of a few points are noise.

## 7. Evidence budget

Everything must fit the model's context, and every token costs money. Tokens are estimated
as characters / 4 (the provider reports exact counts after the call). Items are kept in
order of value until the 12,000-token budget is used: signals (short and certain), hunks
(the change itself), enclosing functions, then related code, with every hunk's best match
before any second-best. What did not fit is counted in `dropped`.
