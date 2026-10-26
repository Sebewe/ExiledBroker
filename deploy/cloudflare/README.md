# The fallback page (Cloudflare Worker)

The domain sits behind Cloudflare (free plan). This Worker passes every request to the Railway web service and, when Railway can't answer, returns a static "Something went wrong, we're investigating" page instead of Railway's error page. It has to live off Railway because a hard usage limit there stops every service; it also covers deploys and crashes. Why, and the decisions behind it: [docs/go-live.md](../../docs/go-live.md) section 5, [docs/decisions.md](../../docs/decisions.md).

Status: built and tested with a stubbed `fetch`, **not deployed** (it needs a Cloudflare account and the domain).

| File | What |
|---|---|
| `worker.mjs` | The entry point: reads `ORIGIN` / `TIMEOUT_MS`, imports the page, calls the handler |
| `handler.mjs` | The logic (no Cloudflare APIs, so it runs under Node) |
| `fallback.html` | The page: self-contained, inline CSS in the Dusk colours, no external requests |
| `wrangler.toml` | Route, `ORIGIN`, timeout, bundling the HTML |
| `handler.test.mjs` | `node:test` suite |

## What it replaces, and what it doesn't

The app answers some errors on purpose: `/api` returns 503 for "no data yet", 404 for an unknown league and 422 for bad arguments, and the frontend turns each into a screen. The Worker must leave those alone. So the app stamps **`X-EB-Origin: app`** on every response it sends (`MarkOrigin` in `src/exiledbroker/api/app.py`: API, static files, 304s, errors). Then:

- A response of 400 or above **with** the stamp is the app's own: passed through untouched, headers and body.
- A response of 400 or above **without** it did not come from the app (Railway's edge: stopped service, deploy, usage limit): replaced.
- A fetch that throws, or whose headers take longer than 15 s: replaced. The timeout is `TIMEOUT_MS`. The slowest legitimate answer is a cold table in a few seconds, so 15 s doesn't cut a healthy origin, and a dead one costs a visitor at most 15 s rather than Cloudflare's 100 s. The timer stops when the headers arrive, so slow bodies are never cut.
- Anything under 400, and every method, header, ETag and 304: passed through unchanged. Bodies are streamed, never buffered. The Worker sets no cache options, so Cloudflare caches exactly what the origin's `Cache-Control` allows (and, as a bonus, a cached asset can still be served while the origin is down).

What visitors get instead (all `Cache-Control: no-store`, `Retry-After: 120`, and `X-EB-Fallback: 1` for debugging):

| Request | Response |
|---|---|
| a page navigation (`Accept: text/html`) | `503`, the HTML page; it reloads itself every 90 s |
| `/api/*` | `502` with `{"detail": "..."}`. Not 503: the frontend reads the API's 503 as "No data yet" (`isNoData`), while any other status shows the detail under "Couldn't load this" |
| anything else (scripts, images) | bare `503` text |

No retries: one failed fetch is enough to show the page, and the page retries by itself.

## Turned away at the edge

Before fetching anything, the Worker answers what the site never sends ([docs/security.md](../../docs/security.md)): any method but GET and HEAD gets 405, except POST under `/api/` (the usage beacon) with a declared body of at most 4 kB (411 without a length, 413 above it). With the `API_LIMITER` rate-limit binding (`wrangler.toml`), an address making more than 60 `/api` requests a minute gets 429 with `Retry-After: 60`. A missing or failing binding lets requests through. None of these reach Railway.

## Caching at the edge

Reads (GET, HEAD) are fetched with `cf: { cacheEverything: true }`, so Cloudflare's edge keeps whatever the origin's Cache-Control allows: tables 30 s and the status 60 s (table URLs carry the data version, `?v=`, so a new hour never gets an older copy), hashed assets a year, index.html and every `/api` error never (`no-cache` / `no-store` from the app). In a traffic spike each Cloudflare location asks Railway for a URL about twice a minute, however many visitors it serves ([hosting.md](../../docs/hosting.md#a-traffic-spike-a-streamer-or-a-video)). Check it live: the second request for a table shows `cf-cache-status: HIT`.

## Deploy

Needs a Cloudflare account with the domain added as a zone (free plan), and Node 24 (`export PATH=~/.local/node/bin:$PATH`).

1. **Deploy the app change first.** The stamp ships in the Railway web service; if the Worker goes live before it, every error response looks foreign and the site shows the fallback page for the app's own 503s and 404s. Check: `curl -sI https://<service>.up.railway.app/api/health | grep -i x-eb-origin`.
2. Edit `wrangler.toml`: `ORIGIN` (the web service's `*.up.railway.app` address, no trailing slash). The route is already `exiledbroker.trade/*`.
3. `cd deploy/cloudflare && npx wrangler login && npx wrangler deploy`
4. DNS is already done (2026-10-25): `exiledbroker.trade` and `www` are proxied `AAAA 100::` records, the anchor the Worker's route needs (a Worker only runs on proxied records; `100::` means no origin, since the Worker sends requests to `ORIGIN` itself). SSL/TLS is Full (strict), Always Use HTTPS is on, and `www` redirects to the root domain ([go-live.md](../../docs/go-live.md) section 3).
5. Change `ORIGIN` later in `wrangler.toml` and redeploy, or in the dashboard (Workers > exiledbroker-fallback > Settings > Variables).

## Test it

- Unit tests (stubbed `fetch`, no network): `node --test "deploy/cloudflare/*.test.mjs"` from the repo root (Node 20+; CI runs them too).
- Locally, without deploying: `npx wrangler dev`, then `curl -i localhost:8787/api/health` (uses the real `ORIGIN`, so only after the web service exists). Set `ORIGIN` to something dead (`http://localhost:9`) to see the fallback.
- After deploying, with the site up: `curl -sI https://<domain>/api/health` shows `x-eb-origin: app`; `curl -sI -H 'If-None-Match: <etag>' https://<domain>/api/missed/<league>` still returns 304. Then stop the web service in Railway for a minute (not the pipeline): a browser shows the page with status 503, `curl -i https://<domain>/api/status` shows the 502 JSON, and starting the service brings the site back with no cache to clear.
- Not verified against Railway's real edge: what its error responses for a stopped service or a hit limit look like. The rule (any 4xx/5xx without the stamp) doesn't depend on it, but do the stop-the-service check above once.

## What it costs

Workers' free plan allows 100,000 requests a day (10 ms CPU each; the Worker does almost no work) as of when this was written; check [Cloudflare's pricing page](https://developers.cloudflare.com/workers/platform/pricing/) before relying on it. Every request on the route counts, static files included. A visitor makes about 1 API request an hour while the tab is open plus the page's files on a first visit (the browser then keeps hashed assets for a year, and requests it answers from its own cache never reach Cloudflare). The Railway simulation measured 28–35 requests per visitor per day ([hosting.md](../../docs/hosting.md#the-railway-bill)), so the free plan covers roughly 3,000 visitors a day. Beyond that the paid plan is $5 a month for 10 million requests. Past the free limit a route "fails closed" by default (visitors see a Cloudflare error); the route's failure mode can be set to fail open in the dashboard so requests go straight to Railway. Cloudflare proxying itself is free and doesn't change Railway's bill, except that cached assets may lower its egress.
