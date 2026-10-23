# Supabase: the off-site backup

The site runs entirely on Railway: web, Postgres and the hourly pipeline, talking over Railway's free private network. Supabase's free tier holds an **off-site copy** of the site's database, in a second provider. The pipeline keeps it up to date after every pass, and it's read back only to restore the site after losing Railway's database. Measurements and the history behind this choice are in [hosting.md](hosting.md#supabase-tried-as-the-database-now-the-off-site-backup).

```
Railway (US East)                                  Supabase (AWS us-east-1, free)
  web ──────── private network ──┐
                                 ├── Postgres (the site's database)
  pipeline (cron, hourly) ───────┘
      │ after each pass: storage/backup.sync          the backup (Postgres 17)
      └──────── session pooler :5432 ───────────────>   uploads the changes,
                                                        reads back ~25 kB
```

**Why it's shaped this way.** Supabase bills what is read out of it (egress, 5 GB a month on the free plan), not what is written in. As the site's main database it needed ~1.4 GB a month and a set of guardrails, and one careless full read could use up the month. As a backup it's written to every hour and read from almost never. Railway's Postgres is next to the services, so reading it is free.

## What a sync does

`storage/backup.py`, `sync(src, dst)`: makes the backup hold what the site's database holds, incrementally, in one transaction on the backup:
- **Per league:** the hours the site has loaded and the backup hasn't (price and loop rows, copied in chunks of 48 hours), and the hours the backup has that the site doesn't are deleted.
- **Shared tables** (leagues, items, tracked items, cards): rows that differ. Tracked items and cards the site no longer has are deleted, and leagues once their rows are gone.
- **Reference data:** the metadata always, the content (RePoE's is ~1 MB) only when its MD5 differs.
- **The Launch tables and the backtest report:** replaced when they've been rebuilt.
- **Raw pages:** the window's pages, and none outside it.
- **A replaced league** (a league switch) is dropped.
- **A league rebuilt by a new `LOADER_VERSION`** (a deploy) is emptied in a transaction of its own, then `VACUUM FULL` gives its space back before the fresh copy goes in. A plain `VACUUM` isn't enough: on the real data the fresh copy still grew the backup from 319 to 439 MB.
- **Checks:** at the end, the row counts on both sides. A mismatch is reported as a warning: it would mean a sync bug.

What it reads back from the backup: which hours and pages it has (one compact string each), the reference checksums, a few counts and stamps. Measured on the real Allflame data, through a byte-counting relay:

| Sync | Read from the backup | Uploaded | Time (local) | Backup size |
|---|---|---|---|---|
| First copy into an empty backup | 6.6 kB | 244 MB | 11 s | 319 MB |
| An hour with nothing new | 24.6 kB | 0.3 MB | 0.3 s | 319 MB |
| Two new hours | 24.7 kB | 0.8 MB | 0.3 s | 319 MB |
| The league rebuilt (new loader), twice in a row | 19.6 kB | 129 MB | 10 s | 319 MB |

So about 18 MB of egress a month at one pass an hour, under 0.5% of the free allowance. Uploads are free.

**The pipeline never fails because of the backup.** With `EB_BACKUP_URL` set, `eb pipeline run` syncs after its pass. An unreachable or failing backup is reported on the pass's log line ("Backup failed (…); the next pass catches up"), with a 10-second connection timeout, and the next pass brings it up to date in one go: a sync adds every hour the backup is missing.

**Tests:**
- `tests/test_backup.py`, on Postgres, covers each case above:
  - after each pass, the backup is identical to the site, and a pass reads under 2 kB back on the fixture;
  - a failed backup doesn't fail the pass;
  - hours and pages leaving the window leave the backup;
  - a rebuilt league is copied afresh;
  - a restore rebuilds the site, and the pipeline carries on from it with one request per new hour;
  - a league switch is dropped from the backup;
  - a backup of the local copy matches a seed.
- `deploy/railway-sim/` has a backup container too. In its league-switch replay, the backup matched the site after every pass, and Mirage's rows and pages left the backup when Allflame took over.

## Commands

```bash
eb pipeline run                          # on Railway, hourly: the pass, then the backup (EB_BACKUP_URL)
EB_BACKUP_URL=… eb site backup -l Allflame              # from the local copy (no EB_DATABASE_URL): the named league
EB_DATABASE_URL=… EB_BACKUP_URL=… eb site backup        # from a site database: mirrored whole
EB_DATABASE_URL=… EB_BACKUP_URL=… eb site restore       # says how big the backup is; --yes restores
```

**Restoring** is the one bulk read of the backup (most of its ~300 MB, about 6% of a month's egress), so `eb site restore` shows the backup's size and does nothing without `--yes`. If the local copy is up to date, `eb site seed --hosted` restores the site from it for free; then the next pass syncs the backup. Restore from the backup when the local copy isn't available.

## The Supabase project (2026-10-23)

- **Project** `qoroikeceewhwqccffrv`, region **us-east-1**, Postgres 17.11, free plan (dashboard: supabase.com, the account that owns it).
- **Data API turned off** (Project Settings → Data API). Keep it off: it serves every `public` table over REST to anyone holding the publishable key, which is public by design. Nothing here uses it.
- **Contents:** seeded fresh on 2026-10-23 (tables emptied, then one `eb site seed --hosted`), from when it was tried as the site's database. Allflame through 2026-10-22 18:00, 672 hours and their raw pages, the Launch history (5 leagues) and picks, the backtest report. 282 MB of the 500 MB, no security advisories. That's already a valid backup: the first Railway pass's sync brings it up to date, uploading the hours since then.
- **Local connection string** in `/Users/sebm/Documents/ExiledBroker/.env.supabase`, one folder above the repo, so it can't be committed. Its `EB_DATABASE_URL` line is the session-pooler URL with a `[YOUR-PASSWORD]` placeholder, and the password is in `SUPABSAE_PASSWORD` (sic). For the commands above it's the **backup** URL (`EB_BACKUP_URL`), never `EB_DATABASE_URL`. Substitute it URL-encoded, and never print it:

  ```bash
  export EB_BACKUP_URL=$(set -a; source ../.env.supabase; set +a; .venv/bin/python -c 'import os, urllib.parse as u
  pw = u.quote(os.environ.get("SUPABASE_PASSWORD") or os.environ["SUPABSAE_PASSWORD"], safe="")
  print(os.environ["EB_DATABASE_URL"].replace("[YOUR-PASSWORD]", pw))')
  ```

- **Supabase MCP** for Claude Code, configured in `/Users/sebm/Documents/ExiledBroker/.mcp.json` (outside the repo). Use it for small metadata queries only (sizes, counts, `get_advisors`): every read is egress.

## The connection string

Use the **session pooler**: Supabase dashboard → Connect → Session pooler.

```
postgresql://postgres.qoroikeceewhwqccffrv:<password>@aws-0-us-east-1.pooler.supabase.com:5432/postgres
```

- **Not the direct connection** (`db.<ref>.supabase.co`): it's IPv6 only, and Railway's outbound IPv6 isn't something we've confirmed.
- **The session pooler holds one server connection for the whole sync**, which its temp tables, its transaction and its `VACUUM FULL` after a rebuild are simplest with. The transaction pooler (port 6543) would hand them different connections.
- **URL-encode the password** (`urllib.parse.quote(pw, safe="")`). Characters like `@ : / # ?` otherwise break the URL. A letters-and-digits password avoids the issue.
- **Connections:** the free plan allows 60; a sync uses one.

## Setting it up on Railway

1. Railway project in **US East**, with Railway's Postgres template and the `web` and `pipeline` services (`deploy/railway/README.md`).
2. On the **pipeline** service only: `EB_BACKUP_URL` = the session-pooler URL above, with the password filled in, as a sealed variable. The web service doesn't need it.
3. Seed Railway's Postgres from the local copy (`eb site seed --hosted`, `deploy/railway/README.md`). The backup is already seeded.
4. Watch the first cron pass's log: it should end with a "Backup: …" line adding the hours since 2026-10-22 18:00, and then "Backup: poe1-… +1/-0 hours" each hour.
5. After a day, check Supabase's Usage page: egress should be well under 1 MB a day of syncs.

## Free-plan limits

| Limit | Ours | What happens |
|---|---|---|
| 500 MB database | ~320 MB at a full window (launch fortnight + latest 14 days; a switch drops the old league); a rebuild doesn't grow it | above it, read-only: syncs fail, and the pipeline reports it and carries on |
| 5 GB egress a month | ~18 MB of syncs; a restore ~300 MB | billed only on paid plans; on free, usage is restricted |
| Paused after 7 days without activity | the hourly sync is activity | if the pipeline stops for a week, resume the project in the dashboard (data is kept) |
| No backups of its own | it *is* the backup; the local copy is the third copy | — |

## Rules

- **Development and tests never touch Supabase:** they use local databases. `tests/conftest.py` blanks `EB_DATABASE_URL` and `EB_BACKUP_URL`. The simulation's backup is a local container.
- **Only the hosted pipeline's sync talks to it** each hour. Plus, when asked, `eb site backup` from the local copy, or a restore.
- **A sync must stay incremental:** it reads which hours and pages the backup has, never their rows. `tests/test_backup.py` budgets a pass's reads from it.
