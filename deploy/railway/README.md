# Railway services

Three services in one Railway project, all from this repo's `Dockerfile`. Each app
service points its **config file path** (Settings → Config-as-code) at its file here.

| Service | Config | What it runs | Volume | Variables |
|---|---|---|---|---|
| web | `deploy/railway/web.json` | uvicorn: the API and the built site (always on) | none | `EB_DATABASE_URL` = Postgres's private URL; `EB_NEXT_LEAGUE` / `EB_NEXT_LEAGUE_START` before a launch (the countdown) |
| pipeline | `deploy/railway/pipeline.json` | `eb pipeline run`, cron `6 * * * *` (runs, then syncs the backup, then exits) | none | `EB_DATABASE_URL` = Postgres's private URL; `EB_BACKUP_URL` = the Supabase backup's session-pooler URL, sealed ([docs/supabase.md](../../docs/supabase.md)); `EB_HEALTHCHECK_URL` = the healthchecks.io ping URL, sealed ([go-live.md](../../docs/go-live.md), item 5); `EB_NEXT_LEAGUE` / `EB_NEXT_LEAGUE_START` before a launch |
| Postgres | Railway's Postgres template | what the site reads (the live league) | the template's | |

Before the first cron run, seed Postgres from the local copy, so the server never
fetches from GGG what we already have (it refuses to run unseeded):

    .venv/bin/eb live sync                 # bring the local copy up to date first
    .venv/bin/eb launch picks              # the Launch history and picks
    .venv/bin/eb backtest run              # the Backtest page's report
    EB_DATABASE_URL=<Postgres's public URL> .venv/bin/eb site seed --hosted

The first pass then fetches only the hours since the seed: one request per hour.
Then it syncs the off-site backup (Supabase, already seeded): its log line ends with
"Backup: …". A failed backup never fails the pass; the next one catches it up. If
Railway's Postgres is ever lost, re-seed it from the local copy as above (free), or
restore it from the backup (`eb site restore`, docs/supabase.md).

Everything here is simulated locally, with Railway's billing, in `deploy/railway-sim/`.
