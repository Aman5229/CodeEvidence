# CodeEvidence dashboard

React + TypeScript (Vite) over the CodeEvidence API: repositories and their stats, PR lists
with filters, PR detail with the diff, the risk score with its reasons and the model's
prediction, and the AI review's findings with their evidence and feedback buttons.

## Run it

The API must be running (see the main README) and allow this origin
(`CORS_ORIGINS`, default `http://localhost:5173`).

```bash
npm install
npm run dev            # http://localhost:5173
```

Create a key with `python -m scripts.create_api_key "dashboard"` and paste it into the
**API key** field at the top. It is kept in this browser only (localStorage).

## Build and deploy

```bash
VITE_API_URL=https://api.example.com npm run build   # static files in dist/
```

`VITE_API_URL` is read at build time (default `http://localhost:8000`). `dist/` can be served
by any static host; the host must send `index.html` for unknown paths, because routing
happens in the browser. Add the dashboard's origin to the API's `CORS_ORIGINS`.

## Typed API client

The types in `src/api/schema.d.ts` are generated from the API's OpenAPI spec, so a renamed
field breaks the build instead of the page. After changing an endpoint or schema:

```bash
python -m scripts.export_openapi     # from the project root: writes frontend/openapi.json
npm run gen:api                      # regenerates src/api/schema.d.ts
```

## How it is built

| Part | Choice |
|---|---|
| Server data | TanStack Query: caching, loading and error states, `useInfiniteQuery` for cursor paging |
| Routing | React Router; PR filters live in the URL, so a filtered list can be shared |
| API calls | `openapi-fetch` with the generated types; the API key is added to every request |
| Feedback | Optimistic: the count changes at once and is rolled back if saving fails |
| Large diffs | Cut at 1,500 lines |
| Styling | Plain CSS with light and dark themes; visible focus outlines |

## Tests

```bash
npm test               # Vitest + Testing Library
npm run lint           # oxlint
npm run build          # type-checks, then builds
```

Not built yet: a Playwright end-to-end smoke test, charts beyond simple bars, syntax
highlighting in diffs, and screenshots in the main README.
