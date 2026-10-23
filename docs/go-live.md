# Going live on Railway

The checklist for putting the site on Railway (Hobby), from the repo review on 2026-10-23, with the decisions taken since. Tick items off here as they land; record the reasoning in [decisions.md](decisions.md). Costs and the simulation are in [hosting.md](hosting.md).

Deadline: the next league launches in about a month. The server must be live, caught up and through a rehearsed league switch before then.

## Decided

- **The server keeps only what the site reads, in Postgres. No DuckDB and no full history on the server.** New hours are fetched as GGG publishes them, loaded, and the raw page is dropped. History pages (Launch market, Conversions) read reduced tables, not the full history. This also removes the pipeline volume and the need to seed one (the old blocker).
- **Seed the server with what we already have, then let it catch up the rest.** Postgres is loaded from the local data: the live league's site rows, the reduced history and the live window's raw pages. The first pass then fetches only the hours since the local copy ended, which also tests that the server recovers after downtime. Never re-fetch from GGG what we already have locally.
- **Raw pages: keep only the live window's, compressed in Postgres** (open question A, option 2). Each new hour's page is stored as it's loaded, and pages that leave the window are deleted. A loader rebuild re-reads them instead of downloading again.
- **No backups.** The data is small and can be fetched again, and the local copy stays.
- **Usage limits are set**, and when the site is down because of them it shows a static "Something went wrong, we're investigating" page. Real traffic can raise the limit; a bug shouldn't be able to eat the credit.
- **The league switch is rehearsed** on historical data before it happens for real, including changed API responses (new items, different order and size).
- **Custom domain:** bought.
- **Uniques:** not a priority. At most, unidentified uniques may later join the tracked items, after go-live.

## Checklist

### 1. Server stores only what the site reads (code)

- [x] `eb pipeline run` writes Postgres directly (`db.site_writer`: in-memory DuckDB with Postgres attached, as `eb live watch` already does), with no data volume. `EB_PUBLISH_URL` / `site.publish` are gone.
- [x] Raw pages in Postgres (`exchange_page`, `EB_EXCHANGE_PAGES=database`): gzipped, written as they're fetched, pruned to the live window after each load (`cx.prune_pages`); the loader reads them before fetching.
- [x] Reduced history for the history pages: only Launch market reads history (Conversions is a static research note, no data). `launch_history` holds each finished league's window medians: 12,332 rows for the five reference leagues instead of 977k hourly; the picks ranked from it are identical on the real data.
- [x] When the live league's fortnight is over, the pipeline captures it into the history and rebuilds the picks (`launch_picks.refresh`); a replaced league's rows are dropped once the new league has data (`site.drop_leagues`).
- [x] `eb site seed --hosted` seeds a new server from the local copy (rows, history, picks, the loaded hours' pages); the pipeline refuses an unseeded database.
- [ ] Re-run the simulation's tiers on the new shape (no volume) and update the bill.

### 2. League switch, rehearsed (works in the local simulation before going live)

What the last four switches on disk show (Settlers → Mercenaries → Keepers → Mirage → Allflame, read from the pages already stored):
- **The old league ends 3–4 days before the next launches.** E.g. Mirage's last trades were 2026-07-20 and Allflame launched 07-24 22:00. In between, only Standard, Hardcore and event leagues (Phrecia, Ancestors) trade. The old league never appears in the hours before a launch.
- **The new league trades in its launch hour.** Allflame had 57 markets at 22:00, then 254, 429 … 1,205 by hour 17. Its first hour is published just after 23:00.
- **The response's shape didn't change across four launches:** the same 8 market keys (`league`, `market_id`, `market_pair`, `volume_traded`, `lowest/highest_stock`, `lowest/highest_ratio`) and the same top level (`markets`, `next_change_id`). Pages grow tenfold in the first hours (165 KB → 1.5 MB).
- **New items trade from the start:** 9 items Allflame traded in its first 4 hours (its own currency, two new cards) had never appeared before; 16 in its first day.

- [x] **Follow the right league through the gap.** The pipeline keeps the league it has (even after it stops trading) and switches only to the announced one, at its first published hour. It no longer falls back to whatever poe.ninja lists first, which in the gap could be Standard or an event. It never picks Standard, Hardcore, Ruthless, SSF or private leagues. The new league's first hour is searched for from a day before the announcement (a handful of pages), not from 2024. Without an announcement, the old league stays and the site says the feed stopped: set `EB_NEXT_LEAGUE` / `_START` on both services.
- [x] **Drop the old league once the new one has data**, keeping its Launch history (captured when its fortnight ended). The pages kept are only the new league's window.
- [x] **The core pool comes from the followed league**: poe.ninja's lists for that league, kept as they are while poe.ninja doesn't list it (an ended league, or a new one poe.ninja hasn't added yet).
- [x] **RePoE lagging behind the launch.** While the exchange trades items RePoE doesn't name, RePoE is rechecked daily instead of weekly. Once they're named, the league is rebuilt from its stored pages (no requests), so an item never splits into a placeholder and its real name.
- [x] **The loader doesn't depend on the page's shape:** shuffled markets, pairs listed the other way round, numbers as floats, unknown fields and pages padded with other leagues give identical rows.
- [x] **The site in the gap** says "Mirage has ended" (with the countdown) instead of "the live feed may have stopped", once a next league is announced.
- [x] Replayed on the real pages (`tests/test_league_switch.py`, `tests/fixtures/league_switch.json.gz`): the hosted pipeline from 2 hours before Allflame's launch to 4 after. Mirage is kept through the gap; Allflame is picked up at its first published hour with ≤ 8 requests; one request per hour after; every endpoint answers.
- [ ] The same switch in the Railway simulation (`deploy/railway-sim/run.py switch`), real containers.

### 3. Railway project (setup)

- [ ] Project with Railway's Postgres template, plus `web` and `pipeline` services pointing their config-as-code at `deploy/railway/web.json` / `pipeline.json`.
- [ ] Variables:
  - web: `EB_DATABASE_URL`;
  - pipeline: `EB_DATABASE_URL` (both set to Postgres's private URL);
  - **both** services: `EB_NEXT_LEAGUE` / `EB_NEXT_LEAGUE_START` before a launch (the web service shows the countdown, the pipeline switches leagues).
- [ ] Custom domain on the web service (CNAME), HTTPS from Railway.
- [ ] Decide whether Railway deploys on every push to `main` or waits for CI (Railway's "wait for CI" setting).

### 4. Seed, then catch up (first run)

- [ ] A seed command loads the server's Postgres from the local data: the live league's site rows, the reduced history, the Launch picks, and the live window's raw pages. It sends nothing to GGG.
- [ ] The first pass then fetches only the hours after the local copy's last hour. Watch it run and check that its `ingest_run` row has one request per missing hour.
- [ ] Afterwards: take the pipeline down for a few hours, bring it back, and check it fetches exactly the missed hours.

### 5. Limits and the fallback page

- [ ] Railway usage settings: an email alert (e.g. $7) and a hard limit (e.g. $10). The hard limit stops the services.
- [ ] Per-service resource caps in Railway (e.g. web 512 MB, pipeline 1 GB), so a runaway is contained before it reaches the limit.
- [ ] **The fallback page can't live on Railway**, since a hard limit stops everything there. Put the domain behind Cloudflare (free). A small Worker passes requests to Railway and returns a static "Something went wrong, we're investigating" page when the origin is down or erroring. It also covers deploys and crashes.
- [ ] Pipeline failure alert: a failed cron pass shows in Railway, and the site shows its stale-feed state. Add an email or uptime ping so someone hears about it.

### 6. Before flipping DNS

- [ ] Finish the cost report (after-fix tiers, the real 24 h run) in [hosting.md](hosting.md#the-railway-bill).
- [ ] Rebuild and check every page on the Railway URL: no data, catching up, live, and stale.

## Settled questions

- **A. Rebuilds without raw pages:** keep the live window's pages compressed in Postgres (about 80 MB), replacing them as new hours arrive (2026-10-23).
- **B. Uniques:** not before go-live, and not a priority.
