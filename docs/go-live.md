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
- **Custom domain:** bought.
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
  - web: `EB_DATABASE_URL`;
  - pipeline: `EB_DATABASE_URL` (both set to Postgres's private URL), `EB_BACKUP_URL` = Supabase's session-pooler URL, sealed ([supabase.md](supabase.md#the-connection-string)), and `EB_HEALTHCHECK_URL` = the healthchecks.io ping URL, sealed (item 5);
  - **both** services: `EB_NEXT_LEAGUE` / `EB_NEXT_LEAGUE_START` before a launch (the web service shows the countdown, the pipeline switches leagues).
- [ ] Custom domain on the web service (CNAME), HTTPS from Railway.
- [ ] Railway waits for CI before deploying a push to `main` (decided 2026-10-23: turn on "Wait for CI" on both app services).
- Go live first on the current league (Allflame) as a demo people can try; the next league launches around 2026-11-13, not announced in detail yet. Set `EB_NEXT_LEAGUE` / `_START` on both services once its name and start time are out.

### 4. Seed, then catch up (first run)

- [ ] A seed command loads the server's Postgres from the local data: the live league's site rows, the reduced history, the Launch picks, and the live window's raw pages. It sends nothing to GGG.
- [ ] The first pass then fetches only the hours after the local copy's last hour. Watch it run and check that its `ingest_run` row has one request per missing hour.
- [ ] Afterwards: take the pipeline down for a few hours, bring it back, and check it fetches exactly the missed hours.
- [ ] The backup: the first pass's log ends with "Backup: …" adding the hours since Supabase's seed (2026-10-22 18:00), then one hour a pass. After a day, Supabase's Usage page shows well under 1 MB of egress a day.

### 5. Limits and the fallback page

- [ ] Railway usage settings: an email alert (e.g. $7) and a hard limit (e.g. $10). The hard limit stops the services.
- [ ] Per-service resource caps in Railway (e.g. web 512 MB, pipeline 1 GB), so a runaway is contained before it reaches the limit.
- [ ] **The fallback page can't live on Railway**, since a hard limit stops everything there. Put the domain behind Cloudflare (free). A small Worker passes requests to Railway and returns a static "Something went wrong, we're investigating" page when the origin is down or erroring. It also covers deploys and crashes. **Built ([deploy/cloudflare/](../deploy/cloudflare/README.md)), not deployed:** the app stamps `X-EB-Origin: app` on every response, and the Worker replaces only errors without it (and failed or 15 s-slow fetches). To do: deploy the app first, then `wrangler deploy`, proxy the DNS record, and check it once by stopping the web service.
- [x] **Pipeline failure alert (built 2026-10-25, set-up steps below).** A failed cron pass shows in Railway and the site shows its stale-feed state, but nobody is told, so each pass pings a dead-man's switch ([healthchecks.io](https://healthchecks.io), free) when `EB_HEALTHCHECK_URL` is set (`ingest/healthcheck.py`, wired in `pipeline.run`): `/start` first, then the bare URL on success or `/fail` with a plain-text reason (up to 4 kB). It counts as a failure when the pass raised, the backup failed (the pass succeeded, but nobody would hear of it otherwise), or the feed looks stopped: the followed league's latest loaded hour ended more than 3 h ago, unless a next league is announced and has no trades yet (then the old league has ended, as the site's banner says). Three hours is two or more passes in a row that loaded nothing: the site's banner warns at 75 min, but an alert should mean an outage, not one late hour. A ping never fails or slows the pass (5 s timeout, one retry, errors swallowed; a miss shows on the pass's line, without the URL). healthchecks.io emails on a `/fail` ping and when no ping arrives in time, which also covers the cron not running at all (Railway stopped by its usage limit, a broken deploy). It mails on a change of state, so a backup that keeps failing is one email, not one an hour.
  - [ ] Set up in healthchecks.io: a check with **period 1 hour, grace 45 minutes** (the pass runs at :06 and takes seconds; the grace absorbs a slow GGG or a Railway cron delay), email as the integration (add a phone/Telegram integration if wanted). Copy its ping URL into the Railway **pipeline** service's variables as `EB_HEALTHCHECK_URL`, sealed. It is a secret: anyone with it can mark the check up or down.
  - [ ] Test it once after going live: pause the pipeline's cron for two hours (or use healthchecks.io's "send test notification") and check the email arrives, then that a pass after resuming turns the check green.
  - [ ] **Web service uptime (a setup step, nothing built):** a free uptime monitor (UptimeRobot, or a second healthchecks.io check on its uptime feature) pinging `https://<domain>/api/status` every 5 minutes with an email alert. It sees the site down; the pipeline's switch can't. Point it at the Cloudflare-fronted domain, not the Railway URL, so it also sees the fallback page cases.

### 6. Before flipping DNS

- [x] Finish the cost report in [hosting.md](hosting.md#the-railway-bill) (the real 24 h run was dropped, 2026-10-23).
- [ ] Rebuild and check every page on the Railway URL: no data, catching up, live, and stale.

## Settled questions

- **A. Rebuilds without raw pages:** keep the live window's pages compressed in Postgres (about 80 MB), replacing them as new hours arrive (2026-10-23).
- **B. Uniques:** out of scope (2026-10-25).
