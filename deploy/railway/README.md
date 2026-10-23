# Railway services

Three services in one Railway project, all from this repo's `Dockerfile`. Each app
service points its **config file path** (Settings → Config-as-code) at its file here.

| Service | Config | What it runs | Volume | Variables |
|---|---|---|---|---|
| web | `deploy/railway/web.json` | uvicorn: the API and the built site (always on) | none | `EB_DATABASE_URL` = Postgres's private URL; `EB_NEXT_LEAGUE` / `EB_NEXT_LEAGUE_START` before a launch (the countdown) |
| pipeline | `deploy/railway/pipeline.json` | `eb pipeline run`, cron `6 * * * *` (runs, then exits) | none | `EB_DATABASE_URL` = Postgres's private URL; `EB_NEXT_LEAGUE` / `EB_NEXT_LEAGUE_START` before a launch |
| Postgres | Railway's Postgres template | what the site reads (the live league) | the template's | |

Before the first cron run, seed Postgres from the local copy, so the server never
fetches from GGG what we already have (it refuses to run unseeded):

    .venv/bin/eb live sync                 # bring the local copy up to date first
    .venv/bin/eb launch picks              # the Launch history and picks
    .venv/bin/eb backtest run              # the Backtest page's report
    EB_DATABASE_URL=<Postgres's public URL> .venv/bin/eb site seed --hosted

The first pass then fetches only the hours since the seed: one request per hour.

Everything here is simulated locally, with Railway's billing, in `deploy/railway-sim/`.
