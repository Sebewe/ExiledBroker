# Going live on Railway

The checklist for putting the site on Railway (Hobby), from the repo review on 2026-10-23, with the decisions taken since. Tick items off here as they land; record the reasoning in [decisions.md](decisions.md). Costs and the simulation are in [hosting.md](hosting.md).

Deadline: the next league launches in about a month. The server must be live, caught up and through a rehearsed league switch before then.

## Decided

- **The server keeps only what the site reads, in Postgres. No DuckDB and no raw pages on the server.** New hours are fetched as GGG publishes them, loaded, and the raw page is dropped. History pages (Launch market, Conversions) read reduced tables, not the full history. This also removes the pipeline volume and the need to seed one (the old blocker).
- **The server catches itself up.** It isn't seeded from the local copy: the first pass fetches what's missing, which also tests that the server can recover after downtime or maintenance.
- **No backups.** The data is small and can be fetched again, and the local copy stays.
- **Usage limits are set**, and when the site is down because of them it shows a static "Something went wrong, we're investigating" page. Real traffic can raise the limit; a bug shouldn't be able to eat the credit.
- **The league switch is rehearsed** on historical data before it happens for real, including changed API responses (new items, different order and size).
- **Custom domain:** bought.
- **Uniques:** not a priority. At most, unidentified uniques may later join the tracked items, after go-live.

## Checklist

### 1. Server stores only what the site reads (code)

- [ ] `eb pipeline run` writes Postgres directly (`db.site_writer`: in-memory DuckDB with Postgres attached, as `eb live watch` already does), with no data volume. Each page is loaded and then dropped. Remove `EB_PUBLISH_URL` / `site.publish` from the hosted path (they stay for local seeding).
- [ ] Reduced history tables for the history pages, built locally from the research DuckDB and published once: Launch market needs the past leagues' tracked-item prices by day, about 52k rows instead of 977k hourly. List what Conversions reads and reduce that the same way.
- [ ] When a league ends, the pipeline adds that league's reduced fortnight to the history tables and rebuilds the Launch picks from those tables, so it never needs the full history.
- [ ] Rebuilds: what happens when `LOADER_VERSION` changes without raw pages on the server (see open question A).
- [ ] Re-run the simulation's tiers on the new shape (no volume) and update the bill.

### 2. Railway project (setup)

- [ ] Project with Railway's Postgres template, plus `web` and `pipeline` services pointing their config-as-code at `deploy/railway/web.json` / `pipeline.json`.
- [ ] Variables:
  - web: `EB_DATABASE_URL`;
  - pipeline: `EB_DATABASE_URL` (both set to Postgres's private URL);
  - **both** services: `EB_NEXT_LEAGUE` / `EB_NEXT_LEAGUE_START` before a launch (the web service shows the countdown, the pipeline switches leagues).
- [ ] Custom domain on the web service (CNAME), HTTPS from Railway.
- [ ] Decide whether Railway deploys on every push to `main` or waits for CI (Railway's "wait for CI" setting).

### 3. Catch-up (first run)

- [ ] The first pass on an empty Postgres fetches the live window: the launch fortnight plus the latest 14 days, at most 672 pages at one a second (about 11 minutes, once). Approved as the catch-up test; watch it run and check its `ingest_run` row.
- [ ] Afterwards: take the pipeline down for a few hours, bring it back, and check it fetches exactly the missed hours.

### 4. Limits and the fallback page

- [ ] Railway usage settings: an email alert (e.g. $7) and a hard limit (e.g. $10). The hard limit stops the services.
- [ ] Per-service resource caps in Railway (e.g. web 512 MB, pipeline 1 GB), so a runaway is contained before it reaches the limit.
- [ ] **The fallback page can't live on Railway**, since a hard limit stops everything there. Put the domain behind Cloudflare (free). A small Worker passes requests to Railway and returns a static "Something went wrong, we're investigating" page when the origin is down or erroring. It also covers deploys and crashes.
- [ ] Pipeline failure alert: a failed cron pass shows in Railway, and the site shows its stale-feed state. Add an email or uptime ping so someone hears about it.

### 5. League switch, rehearsed

- [ ] Study the real switches on disk: GGG's pages across the last league changes (Settlers → … → Mirage → Allflame). What changes at launch: new league keys, new items, item order, response size, the first hours' thin markets, and RePoE lagging behind new items.
- [ ] Replay a switch through the hosted pipeline in the simulation: `EB_NEXT_LEAGUE` set, the old league running, the new league's first pages. It must switch exactly at launch, drop the old league from the site, add its reduced fortnight to history, rebuild the picks, and show "waiting for the first trades" to the first hour.
- [ ] Make the loader agnostic to response shape: no reliance on item order or count, unknown items (not yet in RePoE) handled without failing or merging, and pages bigger than any seen so far fine. Test with recorded pages, reordered and padded, and with RePoE missing the new items.

### 6. Before flipping DNS

- [ ] Finish the cost report (after-fix tiers, the real 24 h run) in [hosting.md](hosting.md#the-railway-bill).
- [ ] Rebuild and check every page on the Railway URL: no data, catching up, live, and stale.

## Open questions

- **A. Rebuilds without raw pages.** Dropping raw pages saves almost nothing: the live window is about 80 MB, roughly $0.01 a month. But a loader change (`LOADER_VERSION`) would then have to download the window again (up to 672 requests) instead of re-reading disk, against the "never re-download" rule. Options:
  - drop them and accept a re-download on a loader change;
  - keep only the live window's pages, compressed in a Postgres table, and delete pages as they leave the window;
  - rebuild locally from the local raw pages and publish.
- **B. Uniques.** Not before go-live (see the reply in the conversation of 2026-10-23): it adds a new data source and new requests, the month is better spent on the league switch, and it can be added once the server is proven.
