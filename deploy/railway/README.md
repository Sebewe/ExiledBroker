# Railway services

Three services in one Railway project, all from this repo's `Dockerfile`. Each app
service points its **config file path** (Settings → Config-as-code) at its file here.

| Service | Config | What it runs | Volume | Variables |
|---|---|---|---|---|
| web | `deploy/railway/web.json` | uvicorn: the API and the built site (always on) | none | `EB_DATABASE_URL` = Postgres's private URL |
| pipeline | `deploy/railway/pipeline.json` | `eb pipeline run`, cron `6 * * * *` (runs, then exits) | `/data` (history + raw pages, ~1.8 GB of 5 GB) | `EB_DATA_DIR=/data`, `EB_PUBLISH_URL` = Postgres's private URL; `EB_NEXT_LEAGUE` / `EB_NEXT_LEAGUE_START` before a launch |
| Postgres | Railway's Postgres template | what the site reads (the live league) | the template's | |

Before the first cron run the pipeline volume must hold the research database and the
raw GGG pages (`data/exiledbroker.duckdb`, `data/raw/ggg/`): the pipeline refuses to
fetch history on an empty volume, so it never re-downloads what we have.

Everything here is simulated locally, with Railway's billing, in `deploy/railway-sim/`.
