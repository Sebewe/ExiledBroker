# Going live on Railway

The checklist for putting the site on Railway (Hobby), from the repo review on 2026-10-23, with the decisions taken since. Tick items off here as they land; record the reasoning in [decisions.md](decisions.md). Costs and the simulation are in [hosting.md](hosting.md).

Deadline: the next league launches in about a month. The server must be live, caught up and through a rehearsed league switch before then.

## Decided

- **The server keeps only what the site reads, in Postgres. No DuckDB and no full history on the server.** New hours are fetched as GGG publishes them, loaded, and the raw page is dropped. History pages (Launch market, Conversions) read reduced tables, not the full history. This also removes the pipeline volume and the need to seed one (the old blocker).
- **Seed the server with what we already have, then let it catch up the rest.** Postgres is loaded from the local data: the live league's site rows, the reduced history and the live window's raw pages. The first pass then fetches only the hours since the local copy ended, which also tests that the server recovers after downtime. Never re-fetch from GGG what we already have locally.
- **Raw pages: keep only the live window's, compressed in Postgres** (open question A, option 2). Each new hour's page is stored as it's loaded, and pages that leave the window are deleted. A loader rebuild re-reads them instead of downloading again.
- ~~**No backups.**~~ Replaced 2026-10-23: **an off-site backup on Supabase's free tier** ([supabase.md](supabase.md)). The pipeline syncs the site's database to it after each pass (uploads only; it reads back ~25 kB), and it's read only to restore. The local copy stays as a third copy.
- **Usage limits are set**, and when the site is down because of them it shows a static "Something went wrong, we're investigating" page. Real traffic can raise the limit; a bug shouldn't be able to eat the credit.
- **The league switch is rehearsed** on historical data before it happens for real, including changed API responses (new items, different order and size).
- **Custom domain:** `exiledbroker.trade`, bought through Cloudflare (so its DNS is Cloudflare's), set up 2026-10-25 (section 3).
- **Uniques:** out of scope (2026-10-25, [decisions.md](decisions.md#scope)): no poller, no tracked uniques.

## Checklist

### 1. Server stores only what the site reads (code)

- [x] `eb pipeline run` writes Postgres directly (`db.site_writer`: in-memory DuckDB with Postgres attached, as `eb live watch` already does), with no data volume. `EB_PUBLISH_URL` / `site.publish` are gone.
- [x] Raw pages in Postgres (`exchange_page`, `EB_EXCHANGE_PAGES=database`): gzipped, written as they're fetched, pruned to the live window after each load (`cx.prune_pages`); the loader reads them before fetching.
- [x] Reduced history for the history pages: only Launch market reads history (Conversions is a static research note, no data). `launch_history` holds each finished league's window medians: 12,332 rows for the five reference leagues instead of 977k hourly; the picks ranked from it are identical on the real data.
- [x] When the live league's fortnight is over, the pipeline captures it into the history and rebuilds the picks (`launch_picks.refresh`); a replaced league's rows are dropped once the new league has data (`site.drop_leagues`).
- [x] `eb site seed --hosted` seeds a new server from the local copy (rows, history, picks, the loaded hours' pages); the pipeline refuses an unseeded database.
- [x] Re-run the simulation's tiers on the new shape (no volume) and update the bill: $2.64 of usage a month at 10 daily visitors, $2.83 at 100, ~$3.2 estimated at 1000 (the 1000 run was interrupted), against the $5 Hobby includes ([hosting.md](hosting.md#the-railway-bill)). Seeded at hour 48 of the league the server's Postgres is 29 MB; a full window is ~280–320 MB with its pages.

### 2. League switch, rehearsed (works in the local simulation before going live)

What the last four switches on disk show (Settlers → Mercenaries → Keepers → Mirage → Allflame, read from the pages already stored):
- **The old league ends 3–4 days before the next launches.** E.g. Mirage's last trades were 2026-07-20 and Allflame launched 07-24 22:00. In between, only Standard, Hardcore and event leagues (Phrecia, Ancestors) trade. The old league never appears in the hours before a launch.
- **The new league trades in its launch hour.** Allflame had 57 markets at 22:00, then 254, 429 … 1,205 by hour 17. Its first hour is published just after 23:00.
- **The response's shape didn't change across four launches:** the same 8 market keys (`league`, `market_id`, `market_pair`, `volume_traded`, `lowest/highest_stock`, `lowest/highest_ratio`) and the same top level (`markets`, `next_change_id`). Pages grow tenfold in the first hours (165 KB → 1.5 MB).
- **New items trade from the start:** 9 items Allflame traded in its first 4 hours (its own currency, two new cards) had never appeared before; 16 in its first day.

- [x] **Follow the right league through the gap.** The pipeline keeps the league it has (even after it stops trading) and switches only to the announced one, at its first published hour. It no longer falls back to whatever poe.ninja lists first, which in the gap could be Standard or an event. It never picks Standard, Hardcore, Ruthless, SSF or private leagues. The new league's first hour is searched for from a day before the announcement (a handful of pages), not from 2024. Without an announcement, the old league stays and the site says the feed stopped: set `EB_NEXT_LEAGUE` / `_START` on both services.
- [x] **Drop the old league once the new one has data**, keeping its Launch history (captured when its fortnight ended). The pages kept are only the new league's window.
- [x] **Price check's paths gain the finished league on the server, with nothing manual** (2026-10-25): the pipeline captures the live league's own paths once its fortnight is over (`price_paths.refresh`, while it is still live, long before the switch) and rebuilds the medians, so the next league's verdicts include it (Allflame's, for the league after it). Only the fitted constants wait for the next local `eb price-check build` and `eb site seed`. Before any re-seed, run `eb price-check build` locally so the seed doesn't overwrite a league the server captured. See [price-check.md](price-check.md#f-pipeline-seed-backup-performance-docs--done-2026-10-25).
- [x] **The core pool comes from the followed league**: poe.ninja's lists for that league, kept as they are while poe.ninja doesn't list it (an ended league, or a new one poe.ninja hasn't added yet).
- [x] **RePoE lagging behind the launch.** While the exchange trades items RePoE doesn't name, RePoE is rechecked daily instead of weekly. Once they're named, the league is rebuilt from its stored pages (no requests), so an item never splits into a placeholder and its real name.
- [x] **The loader doesn't depend on the page's shape:** shuffled markets, pairs listed the other way round, numbers as floats, unknown fields and pages padded with other leagues give identical rows.
- [x] **The site in the gap** says "Mirage has ended" (with the countdown) instead of "the live feed may have stopped", once a next league is announced.
- [x] Replayed on the real pages (`tests/test_league_switch.py`, `tests/fixtures/league_switch.json.gz`): the hosted pipeline from 2 hours before Allflame's launch to 4 after. Mirage is kept through the gap; Allflame is picked up at its first published hour with ≤ 8 requests; one request per hour after; every endpoint answers.
- [x] The same switch in the Railway simulation (`deploy/railway-sim/run.py switch`, real containers): Mirage kept with the countdown at 21:06 and 22:06; Allflame live at 23:06 (9.7 s, Mirage dropped); then one hour a pass in 2–3 s. 8 exchange requests in 7 passes, and the core pool's Allflame lists downloaded once. Rerun with the backup container (2026-10-23): every pass synced it, Mirage's rows and 339 pages left it at the switch, and it matched the site at the end.

### 3. Railway project (setup)

- [ ] Project with Railway's Postgres template, plus `web` and `pipeline` services pointing their config-as-code at `deploy/railway/web.json` / `pipeline.json`.
- [ ] Variables:
  - web: `EB_DATABASE_URL`, and `EB_ADMIN_TOKEN` (32+ random characters, sealed) for the admin page ([admin.md](admin.md));
  - pipeline: `EB_DATABASE_URL` (both set to Postgres's private URL), `EB_BACKUP_URL` = Supabase's session-pooler URL, sealed ([supabase.md](supabase.md#the-connection-string)), and `EB_HEALTHCHECK_URL` = the healthchecks.io ping URL, sealed (item 5);
  - **both** services: `EB_NEXT_LEAGUE_START=2026-11-13` now (the date is all GGG has announced: it turns the pre-launch preview on, section 11, and the pipeline ignores a date alone), then `EB_NEXT_LEAGUE` and the full time once they're announced (the web service shows the countdown, the pipeline switches leagues).
- [x] **Domain on Cloudflare (2026-10-25).** `exiledbroker.trade` and `www` are proxied `AAAA 100::` placeholder records (Cloudflare's "no origin" address, until launch: then the root record points at Railway, section 7). SSL/TLS is Full (strict), Always Use HTTPS is on, and a redirect rule sends `www` to the root domain (301, path and query kept). HSTS is off until the site is live. Until the Worker is deployed the domain answers 522 (no origin).
- [ ] Deploy the Worker once the web service is up: `ORIGIN` in `deploy/cloudflare/wrangler.toml` (the route is already `exiledbroker.trade/*`), `npx wrangler login` (interactive, the user) and `npx wrangler deploy`.
- [ ] Optional: Cloudflare Access (free) on `/admin*` and `/api/admin*` in front of the admin token ([admin.md](admin.md#once-deployed)).
- [ ] Railway waits for CI before deploying a push to `main` (decided 2026-10-23: turn on "Wait for CI" on both app services).
- ~~Go live first on the current league (Allflame) as a demo people can try.~~ Replaced 2026-10-26: go live with the **pre-launch preview** (section 11), Allflame rewound to its first week. The next league launches 2026-11-13 (PST); its name and time aren't announced yet. Set `EB_NEXT_LEAGUE` and the full `EB_NEXT_LEAGUE_START` on both services once they're out.

### 4. Seed, then catch up (first run)

- [ ] A seed command loads the server's Postgres from the local data: the live league's site rows, the reduced history, the Launch picks, and the live window's raw pages. It sends nothing to GGG.
- [ ] The first pass then fetches only the hours after the local copy's last hour. Watch it run and check that its `ingest_run` row has one request per missing hour.
- [ ] Afterwards: take the pipeline down for a few hours, bring it back, and check it fetches exactly the missed hours.
- [ ] The backup: the first pass's log ends with "Backup: …" adding the hours since Supabase's seed (2026-10-22 18:00), then one hour a pass. After a day, Supabase's Usage page shows well under 1 MB of egress a day.

### 5. Limits and the fallback page

- [ ] Railway usage settings: an email alert (e.g. $7) and a hard limit (e.g. $10). The hard limit stops the services.
- [ ] Per-service resource caps in Railway (e.g. web 512 MB, pipeline 1 GB), so a runaway is contained before it reaches the limit.
- [ ] **Read the real memory after the first week** (Railway, each service's Metrics tab): the web service should sit near 0.1–0.2 GB and Postgres near 0.1 GB ([hosting.md](hosting.md#memory)). The image already sets polars' allocator to give memory back (`_RJEM_MALLOC_CONF`, nothing to configure). If usage heads past ~$4 a month, the levers in order: (1) Postgres's `shared_buffers` from 128 MB to 32–64 MB (Postgres service, Data tab: `ALTER SYSTEM SET shared_buffers = '64MB';` then restart the service), after checking in the simulation that the page cache doesn't take the same memory back; (2) import DuckDB only where it's used (~20 MB on the web); (3) the $0 setup in hosting.md, which needs incremental Price check items first.
- [ ] **The fallback page can't live on Railway**, since a hard limit stops everything there. Put the domain behind Cloudflare (free). A small Worker passes requests to Railway and returns a static "Something went wrong, we're investigating" page when the origin is down or erroring. It also covers deploys and crashes. **Built ([deploy/cloudflare/](../deploy/cloudflare/README.md)), not deployed:** the app stamps `X-EB-Origin: app` on every response, and the Worker replaces only errors without it (and failed or 15 s-slow fetches). To do: deploy the app first, then `wrangler deploy`, proxy the DNS record, and check it once by stopping the web service.
- [x] **Pipeline failure alert (built 2026-10-25, set-up steps below).** A failed cron pass shows in Railway and the site shows its stale-feed state, but nobody is told, so each pass pings a dead-man's switch ([healthchecks.io](https://healthchecks.io), free) when `EB_HEALTHCHECK_URL` is set (`ingest/healthcheck.py`, wired in `pipeline.run`): `/start` first, then the bare URL on success or `/fail` with a plain-text reason (up to 4 kB). It counts as a failure when the pass raised, the backup failed (the pass succeeded, but nobody would hear of it otherwise), or the feed looks stopped: the followed league's latest loaded hour ended more than 3 h ago, unless a next league is announced and has no trades yet (then the old league has ended, as the site's banner says). Three hours is two or more passes in a row that loaded nothing: the site's banner warns at 75 min, but an alert should mean an outage, not one late hour. A ping never fails or slows the pass (5 s timeout, one retry, errors swallowed; a miss shows on the pass's line, without the URL). healthchecks.io emails on a `/fail` ping and when no ping arrives in time, which also covers the cron not running at all (Railway stopped by its usage limit, a broken deploy). It mails on a change of state, so a backup that keeps failing is one email, not one an hour.
  - [ ] Set up in healthchecks.io: a check with **period 1 hour, grace 45 minutes** (the pass runs at :06 and takes seconds; the grace absorbs a slow GGG or a Railway cron delay), email as the integration (add a phone/Telegram integration if wanted). Copy its ping URL into the Railway **pipeline** service's variables as `EB_HEALTHCHECK_URL`, sealed. It is a secret: anyone with it can mark the check up or down.
  - [ ] Test it once after going live: pause the pipeline's cron for two hours (or use healthchecks.io's "send test notification") and check the email arrives, then that a pass after resuming turns the check green.
  - [ ] **Web service uptime (a setup step, nothing built):** a free uptime monitor (UptimeRobot, or a second healthchecks.io check on its uptime feature) pinging `https://<domain>/api/status` every 5 minutes with an email alert. It sees the site down; the pipeline's switch can't. Point it at the Cloudflare-fronted domain, not the Railway URL, so it also sees the fallback page cases. Use **GET**, not HEAD: the app's routes answer GET only, so a HEAD check gets 405.

### 7. A traffic spike (a streamer or a video)

What tens of thousands of visitors at once would do, and the fixes: [hosting.md](hosting.md#a-traffic-spike-a-streamer-or-a-video). The code side is done (2026-10-25: edge caching in the Worker, `?v=` on table URLs, `no-store` by default, one computation per key, a slim item cache, settings no longer rebuilt per request). At launch:

- [ ] **Point the domain at Railway.** Add `exiledbroker.trade` as a custom domain on the web service, then replace the root `AAAA 100::` record with the proxied CNAME Railway shows (`www` can stay a placeholder: the redirect rule answers it). Failing open, and assets bypassing the Worker, both go to the DNS target, so it must be the real origin. Keep `ORIGIN` set to the `*.up.railway.app` address.
- [ ] **Assets bypass the Worker:** Workers Routes, add `exiledbroker.trade/assets/*` with Worker **None**. The CDN serves them (immutable for a year) without counting against the Worker's 100,000 requests a day.
- [ ] **The route fails open** (Workers Routes, the route's request limit failure mode), so a spent quota sends visitors to Railway instead of an error.
- [ ] **Check the cache works:** `curl -sI "https://exiledbroker.trade/api/missed/<league>?v=<data_version>"` twice: the second shows `cf-cache-status: HIT`; an asset shows `HIT` too; `/api/health` shows `no-store` and is never a hit.
- [ ] **Turn on Cloudflare Web Analytics** for the domain (Analytics & Logs, Web Analytics, automatic setup: free and cookie-free, so no consent banner). The page's Content-Security-Policy already allows its beacon (`static.cloudflareinsights.com`, `cloudflareinsights.com`). It's how we'll see a spike in visitors, not only in requests.
- [ ] **Our own usage counts** ([usage.md](usage.md)): set `EB_ADMIN_TOKEN` (a long random string, `openssl rand -hex 32`) on the web service, make sure the deployed Worker passes `x-eb-client-ip` (the API hardening's), then check `curl -s -H "Authorization: Bearer $EB_ADMIN_TOKEN" https://exiledbroker.trade/api/stats` shows `"stored": true` and counts a page you just opened (after the 5-minute flush; the stats call flushes too).
- [ ] If a spike is coming or happening (Workers analytics nearing 100k a day): Workers Paid, $5 a month for 10 million requests.

### 6. Before flipping DNS

- [x] Finish the cost report in [hosting.md](hosting.md#the-railway-bill) (the real 24 h run was dropped, 2026-10-23).
- [ ] Rebuild and check every page on the Railway URL: no data, catching up, live, and stale.
- [ ] **Smoke-test every deploy** (built 2026-10-26): `.venv/bin/eb site smoke https://exiledbroker.trade --edge --origin https://<service>.up.railway.app` fetches every page, the built files index.html names, `og.png`, `robots.txt` and every endpoint the pages call for the newest league (≈30 requests to our site, nothing upstream), and checks the answers: 200s with ETags and 304s, edge cache hits, unknown routes and a previous deploy's chunk 404, `/api/stats` and `/api/admin` closed, the origin refusing requests without the key. It exits 1 on a failure; a late feed is only a warning. Before DNS points at Railway, run it without `--edge` against the Railway address (with the origin key not yet set).

### 8. Abuse protection (Cloudflare and Railway settings)

The code side is done (2026-10-26, [security.md](security.md)): the Worker refuses methods and bodies the site never sends and limits each address on `/api`, the app can refuse anything that didn't come through Cloudflare, the API docs are off in the image. These need the dashboards, in this order:

- [ ] **Origin key, Cloudflare side first.** Generate one: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. Rules > Transform Rules > Modify Request Header > create: when Hostname equals `exiledbroker.trade` (all incoming requests), **Set static** header `X-EB-Origin-Key` to the key. It covers every path to Railway: through the Worker, the assets route that bypasses it, and the route failing open.
- [ ] **Then the Railway side:** the web service's variable `EB_ORIGIN_KEY` = the same key, sealed. Not before the rule exists, or every visitor gets 403. Check: `curl -s -o /dev/null -w '%{http_code}' https://<service>.up.railway.app/api/status` gives 403, the same through `https://exiledbroker.trade` gives 200, and `/api/health` on the Railway address still gives 200 (Railway's health check). Rotating the key: change the rule, then the variable, within a minute.
- [ ] **The Worker's rate limiter** deploys with it (`[[ratelimits]]` in `wrangler.toml`, 60 `/api` requests a minute per address). After `npx wrangler deploy`, check the binding shows under the Worker's Settings > Bindings. A quick loop of 70 `curl`s at `/api/status` should end in 429s.
- [ ] **WAF rate-limiting rule** (Security > WAF > Rate limiting rules; the free plan has one): if URI Path starts with `/api/`, counting by IP, more than 50 requests in 10 seconds, Block for 10 seconds. It acts before the Worker, so a flood doesn't spend the Worker's daily quota.
- [ ] **Bot Fight Mode** (Security > Bots) on, and "Block AI bots" on. Then check the uptime monitor (section 5) still gets 200 from `/api/status`; if it's challenged, turn Bot Fight Mode off (the free plan can't exempt one client).
- [ ] **Emergency lever, know where it is:** Security > Settings > Security level "I'm under attack" puts a browser check in front of every visitor. Turn it on only during an attack: it also stops the uptime monitor.
- [ ] **GitHub:** Settings > Code security, turn on Dependabot alerts (free), so a vulnerable dependency is reported. Run `pip-audit` and `npm audit` once more before flipping DNS.
- [ ] **Admin panel** (when it ships): `EB_ADMIN_TOKEN` on the web service, 32+ random bytes, sealed. Optionally Cloudflare Access (Zero Trust, free up to 50 users) on `/admin*` and `/api/admin*`.

### 9. Launch day (the next league)

The site matters most in a league's first hours, when traffic peaks and the data is thinnest. Times in UTC; GGG announces the launch time about a week ahead.

- **Until then** only `EB_NEXT_LEAGUE_START=2026-11-13` is set (section 11): the site shows the preview and the launch date, and the pipeline keeps following Allflame.
- **When the launch time is announced:** set `EB_NEXT_LEAGUE` (the league's exact name) and `EB_NEXT_LEAGUE_START` (e.g. `2026-11-13T20:00:00Z`) on **both** services and redeploy them. The web service shows the countdown; the pipeline keeps the old league until the new one's first published hour, then switches (section 2). No command is run by hand: the hosted pipeline finds the launch hour itself, from a day before `_START`. (Locally, `eb live sync -l <Name>` does the same for the research copy.) A wrong name or time only delays the switch: the pipeline searches from a day before `_START` and never picks Standard or an event league. Fix the variable and the next pass catches up.
- **The day before:** run `eb site smoke` (section 6); check healthchecks.io is green and the uptime monitor is up; look at Railway's usage against the limits (section 5) and consider Workers Paid if a streamer is expected (section 7). Don't merge anything risky in the 24 hours around the launch.
- **Hour zero** (the league opens at `:00`): the site shows the countdown, then "waiting for the first trades". GGG publishes the first hour a few minutes after it ends; the pass at the next `:06` loads it (≤ 8 requests to find it, then one an hour). Each page's empty and one-hour states are tested (`tests/test_league_switch.py`, the frontend's no-data tests). If the first hour hasn't loaded by `:30` after it ended, look at the pipeline's log in Railway (each pass prints one line saying what it loaded); a pass that found nothing new is retried by the next one, and the healthchecks.io email comes after 3 hours without data.
- **The first day:** new currency (the league's own items) shows in Price check only once poe.ninja lists the new league (its lists decide the core pool) and RePoE names it (rechecked daily while the exchange trades unnamed items, then the league rebuilds from stored pages with no requests). Both lag by hours to a day; nothing to do but check it happened.
- **If something breaks:** the fallback page covers the web service being down; the healthchecks.io email covers the pipeline. Roll back (section 10) rather than fixing forward under load, unless the fix is one line.

### 10. Rolling back

- **Code (either service):** Railway, the service, Deployments: pick the last good deployment and *Redeploy* (Railway calls it Rollback). It's the same image, so it takes about a minute. Then `eb site smoke`. Roll back the web and the pipeline separately: they share the database, not the code.
- **The database survives a rollback.** `schema.sql` only ever adds (`CREATE … IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`), so older code runs on a newer schema. The one cost: a rollback across a `LOADER_VERSION` bump makes the pipeline rebuild the league from its stored pages (no requests to GGG, a minute or two of CPU), and rolling forward again rebuilds once more.
- **Browsers and the edge:** the frontend's tables carry the code version in `?v=` and the saved cache is dropped on a new build, so nobody keeps the bad build's data. An open tab on the bad build reloads itself the first time it opens a page whose code is gone (`web/src/lib/chunkReload.ts`).
- **Data:** a bad load or a corrupted database is fixed by re-seeding from the local copy (`eb site seed --hosted`, free) or, without it, restoring from the off-site backup (`eb site restore`, ~300 MB of Supabase egress, behind `--yes`). Both need the pipeline's cron paused first so a pass doesn't run mid-way.
- **DNS or Cloudflare:** the Worker's previous version is one click away (Workers, the Worker, Deployments, *Rollback*). To take the Worker out entirely, delete its route: the proxied DNS record then goes straight to Railway.

If Railway's signups are still closed when it's time to deploy, [hosting.md](hosting.md#if-railway-stays-closed-flyio-or-render) compares Fly.io and Render and lists what changes in this checklist.

### 11. The preview and the Reddit announcement

Before the launch the site is a **preview** ([preview.md](preview.md)): Allflame rewound to its first week, with a day picker and a "what happened next" reveal. It's how the site is first announced (Reddit, [announcement.md](announcement.md)) and how the first usage numbers come in. It turns itself off when the announced league's first trades load: nothing to deploy on launch day.

**Switching it on** (once Railway is up, sections 3 and 4):

- [ ] Build the snapshot on the laptop, where `data/` has Allflame's pages: `eb preview build --league Allflame --days 1,3,5,7` (no requests to GGG; run it detached if it says it'll take more than a few minutes). It writes `preview_snapshot` in the local DuckDB.
- [ ] Copy it to the server with the rest: `eb site seed --hosted` (a first seed), or `eb site seed` afterwards. A rebuild gets a new `version`, so browsers and Cloudflare pick it up within the hour.
- [ ] Set `EB_NEXT_LEAGUE_START=2026-11-13` on **both** services, and nothing else about the next league yet. With only a date, `/api/status` has `upcoming` (`name` null, `time_known` false), so `EB_PREVIEW=auto` (the default) shows the preview, and the strip shows the date with no countdown. The pipeline ignores a date alone: `pipeline.pick_league` switches leagues only once both `EB_NEXT_LEAGUE` and a full time are set, so it keeps following Allflame (one request an hour, as before).
- [ ] `eb site smoke https://exiledbroker.trade --edge` checks the preview too: the manifest under its version (and that it's `/api/status`'s), the default day's recap, Launch market, Price check and one item, the item's "what happened next" series, all cached a day at the edge, and a missing key is 404. A league announced with no preview showing is a warning (`preview`): the snapshot isn't seeded or `EB_PREVIEW=off`.
- [ ] Open the site at phone width and on a desktop: the Preview label, the day picker on the recap, Price check and Launch market, the reveal, no stale-feed banner.

**When the name and time are announced** (about a week before): set `EB_NEXT_LEAGUE` and the full `EB_NEXT_LEAGUE_START` (e.g. `2026-11-13T20:00:00Z`) on both services (section 9). The strip gains the countdown. The preview stays on until the new league's first hour is loaded, then `/api/status` drops it and every open page shows the live league on its next status check. If the name is never set, the preview stays on and the pipeline never switches: setting both is what ends it.

**Turning it off by hand** (a broken snapshot, or to stop it early): `EB_PREVIEW=off` on the web service and redeploy. The pages fall back to the live league (Allflame, shown as ended, with the next league's date).

**Usage counts.** The preview's own events (`feature:preview-day`, `feature:preview-reveal`, `feature:preview-cta`, and the trading game's `game-trade` / `game-step`) show on `/admin` with the rest ([usage.md](usage.md#the-preview)). Whether to reset the counts at launch is left for then; `usage_daily` is per day, so the launch's numbers can be read from Nov 13 on either way.

**Spike readiness before posting** (an earlier screenshot post got ~6k views; a link brings visitors in a burst over a few hours, all on the same few URLs):

- [ ] Sections 7 and 8 are done: assets bypass the Worker, the route fails open, the origin key and rate limits are set, Web Analytics is on.
- [ ] **The Worker's daily 100k requests is the first limit.** Assets bypass it, but every `/api` request and every beacon (`/api/hit`, one per page view and per feature used) counts. A preview visitor who picks a couple of days and opens a few items makes ~20–30 Worker requests, so 100k a day is ~3,000–5,000 visitors. Turn on **Workers Paid ($5, 10M requests) the day of the post**, and back off it after the spike if Workers analytics shows it isn't needed.
- [ ] **The origin barely notices.** Every preview document is one stored blob served from memory, with `public, max-age=86400` under the snapshot's version, so Cloudflare answers repeats from the edge; `/api/status` is the only uncached request a visitor repeats (about once an hour). Check `cf-cache-status: HIT` on `/api/preview/manifest?v=<version>` (the smoke check does) before posting.
- [ ] **Rate limits fit a curious visitor:** the Worker allows 60 `/api` requests a minute per address and the WAF rule 50 in 10 seconds. Clicking through all four days of the recap and Price check stays well under, but a few people behind one address (a university, a café) can hit it: if Reddit comments mention 429s, raise the Worker's limit (`wrangler.toml`) rather than turning it off.
- [ ] Railway's usage alert and hard limit (section 5) are set, and the fallback page works: a spike that hits the limit shows "we're investigating", not an error.
- [ ] Post when you can watch it for the first couple of hours: Workers analytics, Railway's Metrics, `/admin`. Post on r/pathofexile first, r/pathofexiledev a day or so later, so the two bursts don't stack.

**After the launch:** put `web/index.html`'s durable `og:description` back (the preview's line names Allflame; the old one is in the comment beside it) and redeploy any time after the switch, and decide about resetting the usage counts.

## Settled questions

- **A. Rebuilds without raw pages:** keep the live window's pages compressed in Postgres (about 80 MB), replacing them as new hours arrive (2026-10-23).
- **B. Uniques:** out of scope (2026-10-25).
