# Security and abuse

The site is public, read-only market data, so the realistic threat isn't a break-in: it's someone scraping or hammering the API until the Railway bill or the Worker quota runs out, or the site goes down. This page is the review of 2026-10-26: what protects the site, what's left, ranked by how likely it is and what it would cost. The settings that need the user's hands are in [go-live.md](go-live.md#8-abuse-protection-cloudflare-and-railway-settings).

## The layers

A request meets these in order. Each one turns away what it can before anything more expensive runs.

| Layer | What it does | Where |
|---|---|---|
| Cloudflare WAF rate-limiting rule (free plan: one rule) | Blocks an address making more than 50 `/api` requests in 10 s, before the Worker runs, so a flood doesn't spend the Worker's 100k-a-day quota | dashboard ([go-live.md](go-live.md#8-abuse-protection-cloudflare-and-railway-settings)) |
| Bot Fight Mode | Challenges known bad bots | dashboard |
| The Worker: methods and bodies | Only GET and HEAD anywhere, POST only under `/api/` with no body or a declared one of at most 4 kB (405 / 411 / 413). Nothing reaches Railway | `deploy/cloudflare/handler.mjs` (`screen`) |
| The Worker: per-visitor limit | 60 `/api` requests a minute per address (the `API_LIMITER` binding), then 429. A visitor's tab makes about one an hour | `handler.mjs` (`withinLimit`), `wrangler.toml` |
| Cloudflare's edge cache | Tables 30 s, status 60 s, assets a year: in a spike each location asks Railway for a URL about twice a minute | `handler.mjs`, the app's Cache-Control ([hosting.md](hosting.md#a-traffic-spike-a-streamer-or-a-video)) |
| Origin lock | With `EB_ORIGIN_KEY` set, the app answers 403 to any request without the matching `X-EB-Origin-Key` header, which a Cloudflare transform rule adds. Calling the public `*.up.railway.app` address directly skips nothing anymore. `/api/health` stays open for Railway's health check | `api/guard.py` (`RequireEdgeKey`) |
| Per-visitor limit at the origin | Behind the lock, the visitor's address is trustworthy (the Worker copies Cloudflare's CF-Connecting-IP into `X-EB-Client-IP`, dropping any value the visitor sent): 120 `/api` requests a minute per address reaching the origin (cache hits don't count), then 429. Bounded memory (50k addresses a minute) | `api/guard.py` (`PerClientLimit`), `EB_API_RATE_LIMIT` |
| uvicorn | `--limit-concurrency 100`: past that it answers 503 at once instead of queueing, so a flood of slow connections can't exhaust memory | `Dockerfile` |
| The API itself | No endpoint takes free-form arguments: every answer is a precomputed view, cached per data version (unknown league or item: a cached 404 check, no query). Concurrent requests for one view compute it once; the item cache is bounded to a league's list | `api/deps.py`, `api/cache.py`, routes |

## What was checked

- **Main's CI:** green (run 58).
- **SQL injection:** every query takes visitor input as a bound parameter (`?` / `%s`). The f-strings in `services/` only interpolate table-name constants and `?` placeholder lists. Route arguments (league, item id) are matched against cached lists before any query sees them.
- **Secrets:** none in the repo (`git ls-files` grep for keys, tokens, passwords, `.env` files), none in the client bundle (the frontend reads no `import.meta.env`). The real ones live in Railway's sealed variables and `../.env.supabase`.
- **Dependencies (2026-10-26):** `pip-audit` on the Python environment and `npm audit` on `web/` (dev dependencies included) report no known vulnerabilities.
- **Docs off in production:** `/docs`, `/redoc` and `/openapi.json` aren't served when `EB_API_DOCS=false`, which the image sets. The frontend's types are still generated from code (`api/schema.py`).
- **CORS:** the site calls its own origin, so it needs none. The image sets `EB_CORS_ORIGINS=[]` (the localhost defaults stay for `npm run dev`). CORS only stops other sites' pages from reading the API in a visitor's browser; it does nothing against scripts, which the layers above handle.
- **Headers already in place:** CSP with hashed inline scripts and `frame-ancestors 'none'`, `nosniff`, `X-Frame-Options: DENY`, a strict referrer policy, `no-store` on API errors (`api/app.py`).
- **Admin and write endpoints:** none on `main` today. The admin panel (being built) is 404 unless `EB_ADMIN_TOKEN` is set, takes a bearer token compared in constant time, and answers `no-store`. The usage beacon (being built) is the first write endpoint: the Worker only lets POST through under `/api/` with a body of at most 4 kB, and both rate limits apply to it.

## Remaining risks, ranked

Likelihood × what it would cost. None of these is likely to take the site down once the go-live settings are in.

1. **Cache-busting floods (likely, low cost).** The `?v=` parameter, or any made-up query string, gives a URL Cloudflare hasn't cached, so each one reaches Railway. The origin answers from its in-memory view cache (well under a millisecond, no database query), and both rate limits cap one address. A botnet spread over many addresses could still push origin CPU and the Worker quota; the lever then is Cloudflare's "Under Attack" mode and Workers Paid ($5 a month). Not fixed in code: stripping query strings at the edge would need the admin panel's and beacon's parameters known first.
2. **Spending the Worker's free quota (plausible, small cost).** 100k requests a day; past it the route fails open (go-live section 7), so the site stays up and Railway takes the traffic, now behind the origin lock and its limit. The WAF rule stops single-address floods before they count. Workers Paid is the fix if it happens twice.
3. **The usage beacon as a write path (plausible once it ships, low to medium cost).** Every POST misses the cache. Its own code should cap the body, batch writes rather than writing a row per request, and answer 204 `no-store`. The edge's 4 kB cap and the limits are in place.
4. **Price check item sweeps (plausible, low cost).** A script requesting every item of a league each hour computes each once (about 900 views an hour, bounded by the item cache and the database pool of 5). That is the same work a busy hour of real visitors causes; the limits make it take many minutes per address.
5. **The admin token leaking (unlikely, medium cost).** It reads metrics, nothing else. Keep it in Railway's sealed variables, 32+ random bytes, and add Cloudflare Access on `/admin*` if wanted.
6. **The origin key leaking (unlikely, low cost).** Someone with it can reach Railway directly, still limited per connection by uvicorn and by the per-address limit (with a forged address header, one address per request, so only uvicorn's cap holds). Rotate: change the transform rule and `EB_ORIGIN_KEY` together.
7. **A vulnerable dependency later (unlikely, low cost).** Nothing is reported today; run `pip-audit` and `npm audit` again before go-live, and turn on GitHub's Dependabot alerts (go-live section 8).
