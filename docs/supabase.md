# Railway + Supabase: connecting them

How to run the site's database on Supabase's free tier, with the web service and the pipeline on Railway, and what's left to finish that integration. Measurements and the reasoning behind it are in [hosting.md](hosting.md#supabase-for-the-database-tried-2026-10-23-fits-after-the-pipeline-fix). This is the reference for doing the switch.

```
Railway (US East)                               Supabase (AWS us-east-1, free)
  web       (always on: /api + the built site) ──┐
                                                  ├─ session pooler :5432 ──> Postgres 17
  pipeline  (cron "6 * * * *", then exits) ──────┘     (what the site reads)
```

Railway's Postgres template is **not** used in this shape: `EB_DATABASE_URL` on both Railway services points at Supabase. Nothing in the code is Supabase-specific; the same URL variable picks the database.

## What exists already (2026-10-23)

- **Supabase project** `qoroikeceewhwqccffrv`, region **us-east-1**, Postgres 17.11, free plan (dashboard: supabase.com, the account that owns it).
- **Data API turned off** (Project Settings → Data API). Keep it off: it serves every `public` table over REST to anyone holding the publishable key, which is public by design. The site talks to Postgres directly and doesn't use it.
- **Seeded** with Allflame through 2026-10-22 18:00 (`eb site seed --hosted`): 672 hours, their raw pages, the Launch history and picks, the backtest report.
- **The pipeline fix that makes it fit** (`db.pushdown`, the `SCHEMA 'public'` attach, reference and page caches by MD5): a pass reads ~1.8 MB from the database instead of ~98 MB. `tests/test_pipeline.py::test_a_pass_never_copies_a_whole_table_out_of_postgres` guards it.
- **Local connection string** in `/Users/sebm/Documents/ExiledBroker/.env.supabase`, one folder above the repo, so it can't be committed. `EB_DATABASE_URL` holds the session-pooler URL with a `[YOUR-PASSWORD]` placeholder, and the password is in `SUPABSAE_PASSWORD` (sic). Substitute it URL-encoded, never print it:

  ```bash
  set -a; source ../.env.supabase; set +a
  export EB_DATABASE_URL=$(.venv/bin/python -c 'import os, urllib.parse as u
  pw = u.quote(os.environ.get("SUPABASE_PASSWORD") or os.environ["SUPABSAE_PASSWORD"], safe="")
  print(os.environ["EB_DATABASE_URL"].replace("[YOUR-PASSWORD]", pw))')
  ```

- **Supabase MCP** for Claude Code, configured in `/Users/sebm/Documents/ExiledBroker/.mcp.json` (outside the repo). Useful read-only calls: `execute_sql` (sizes, row counts, `extensions.pg_stat_statements`), `get_advisors` (security / performance). It can't hand out the database password and isn't needed for seeding.

## The connection string

Use the **session pooler**: Supabase dashboard → Connect → Session pooler.

```
postgresql://postgres.qoroikeceewhwqccffrv:<password>@aws-0-us-east-1.pooler.supabase.com:5432/postgres
```

- **Not the direct connection** (`db.<ref>.supabase.co`): it's IPv6 only, and Railway's outbound IPv6 isn't something we've confirmed.
- **Not the transaction pooler** (port 6543): the pipeline holds a transaction open across many statements through DuckDB's postgres extension (ATTACH, `COPY`, `postgres_execute`), which needs one server connection for the whole session. The web pool (`db._pool`) already disables prepared statements, but the pipeline is what rules it out.
- **URL-encode the password** (`urllib.parse.quote(pw, safe="")`). Characters like `@ : / # ?` otherwise break the URL. A letters-and-digits password avoids the issue.
- Optionally append `?sslmode=require`. libpq's default (`prefer`) already uses TLS with the pooler; `require` refuses a plaintext fallback. (Not yet tried with the pipeline's DuckDB attach; check one pass if you add it.)
- **Connections:** the free plan allows 60. The web service pools at most 5 (`db._pool`), and a pipeline pass opens a few, one at a time.

## Steps to finish the integration

1. **Railway project, US East region**, with only the two app services: `web` and `pipeline` from this repo, config-as-code at `deploy/railway/web.json` / `pipeline.json`, "Wait for CI" on. Don't add the Postgres template.
2. **Variables on both services** (Railway → service → Variables; a shared variable is simplest):
   - `EB_DATABASE_URL` = the session-pooler URL above, with the password filled in. Mark it as sealed/secret.
   - `EB_NEXT_LEAGUE` / `EB_NEXT_LEAGUE_START` once the next league is announced (launch around 2026-11-13).
3. **Free the dead space first.** The project is at ~488 MB of its 500 MB (re-seeds during the trial left dead rows; `VACUUM` made them reusable but didn't shrink the files). Above 500 MB Supabase makes the database read-only. Empty the site tables, then seed once:

   ```sql
   -- via psql / psycopg on the session pooler: empties every table in public (the site's
   -- copy; the local DuckDB is the source). TRUNCATE frees the space at once.
   DO $$ BEGIN
     EXECUTE (SELECT 'TRUNCATE ' || string_agg(format('%I.%I', schemaname, tablename), ', ')
                     || ' CASCADE' FROM pg_tables WHERE schemaname = 'public');
   END $$;
   ```

   This needs the user's go-ahead (it's destructive, and auto mode blocks it). Expect ~282 MB after the seed. Re-seeding is a DELETE then COPY, so **always TRUNCATE before re-seeding** a free project rather than seeding on top.
4. **Seed from the local copy**, never from GGG (`eb pipeline run` refuses an unseeded database):

   ```bash
   .venv/bin/eb live sync         # local copy up to date (the user runs the live feed)
   .venv/bin/eb launch picks      # Launch history and picks
   .venv/bin/eb backtest run      # the Backtest page's report
   EB_DATABASE_URL=<session pooler URL> .venv/bin/eb site seed --hosted
   ```

   Takes ~2–3 minutes from home (uploads are free; Supabase bills egress, not ingress). Check that no `eb live watch` is writing the local DuckDB while it runs.
5. **First cron pass:** watch its log in Railway. It should fetch exactly the hours since the seed (one request per missing hour; `ingest_run` records it) and finish in seconds from US East. Then check `/api/status` and the pages on the Railway URL.
6. **After a day:** Supabase dashboard → Usage. Egress should be ~70–100 MB a day (about 1.8 MB a pass, plus ~0.8 MB when the web service rebuilds its cached views each hour). Much more means a statement is copying a table again: look at `extensions.pg_stat_statements` for `COPY (SELECT … ctid BETWEEN …)` with high row counts.
7. **Update the docs that describe the old shape:** `deploy/railway/README.md` (Postgres row, "Postgres's private URL"), `docs/go-live.md` section 3, `docs/hosting.md` "Shape", `docs/decisions.md` (a dated entry: database on Supabase, why), and the hosting target in `CLAUDE.md`.

## Free-plan limits to keep in mind

| Limit | Ours | What happens |
|---|---|---|
| 500 MB database | ~282 MB at a full window (launch fortnight + latest 14 days; a league switch drops the old one) | above it, read-only: the pipeline's writes fail |
| 5 GB egress a month | ~2–3 GB estimated | billed only on paid plans; on free, usage is restricted |
| Paused after 7 days without activity | the hourly pipeline is activity | if the pipeline stops for a week, the site's database pauses: resume it in the dashboard (data is kept) |
| 500 MB RAM, shared CPU | the site's reads are small and cached | — |
| No backups | decided: none needed | re-seed from the local copy |

## Going back to Railway's Postgres

Add Railway's Postgres template, set `EB_DATABASE_URL` on both services to its private URL, seed it the same way, and pause the Supabase project. Nothing in the code changes. The pipeline fix stays useful there too: shorter passes, less CPU.
