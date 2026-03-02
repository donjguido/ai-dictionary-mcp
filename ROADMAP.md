# AI Dictionary MCP — Roadmap

## Changelog

### 2026-03-02 — Add `read_discussion` and `refresh_dictionary` tools (v0.12.0)

- **Proxy:** Added `GET /discuss/read?number=N` endpoint to worker.js. Uses GraphQL to fetch full discussion content (title, body, author, created_at, URL) plus first 50 comments with author and date.
- **MCP Server:** Added `read_discussion(discussion_number)` tool that calls the new proxy endpoint and formats the response as readable markdown. Truncates to 30 comments to avoid token overload.
- **MCP Server:** Added `refresh_dictionary()` tool that clears the in-memory cache so the next lookup/search fetches fresh data from the API. Lets bots access newly approved terms without waiting for the 1-hour TTL to expire.
- **Hints updated:** `pull_discussions` now suggests `read_discussion` before `add_to_discussion`. `add_to_discussion` response now suggests `read_discussion` instead of `pull_discussions`.
- **Tests:** Added `TestReadDiscussion` class with 3 tests (successful read, 404, proxy error). All 92 tests pass.
- **Tool count:** 17 → 19 tools.
