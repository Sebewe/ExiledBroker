# Pre-launch preview

Before the next league launches (Nov 13, PST), the site shows a **preview**: the whole
site rewound to Allflame's early days, with a day picker (days 1, 3, 5 and 7, default
5) and a "what happened next" reveal. Everything shown is real data from a snapshot
built locally. It turns itself off when the announced league's first trades load, so
launch day needs no deploy. The plan and the work split are in the design artifact and
`/mnt/project-files/preview/handoff.md`; this page is the contract the code follows.

## The snapshot

`preview_snapshot(key, built_at, body)`: one gzipped JSON document per key
(`storage/schema.sql`), written by `eb preview build` locally, copied to the site by
`eb site seed`. `src/exiledbroker/preview/snapshot.py` owns the keys; every document is
checked against its model when written (`snapshot.put`), so the route never has to.

| Key | Model | What |
|---|---|---|
| `manifest` | `PreviewManifest` | league, launch, the days (each with the league as `/api/status` listed it then), default day, `next_until`, `built_at`, `version` |
| `d{day}/missed` | `list[MissedWindow]` | the Market recap at the end of that day |
| `d{day}/price-check` | `PriceCheckIndex` | Price check's list |
| `d{day}/price-check/{item_id}` | `PriceCheckItem` | one item, for every listed item |
| `d{day}/launch-picks` | `list[LaunchWindow]` | the Launch market |
| `d{day}/recap-next` | `PreviewRecapNext` | each of that day's recap trades (loops, cards, flips): did it pay in each of the next 24 hours |
| `next/price-check/{item_id}` | `PreviewItemNext` | the item's series from launch to day 10, for the reveal |

`day` is the launch day, 1-based: the site as it stood at the end of that day
(`launch + day × 24 h`). The Backtest page stays live. `version` must change with
every build: browsers and Cloudflare cache documents under it.

A sample snapshot, `web/src/test/preview_sample.json` (days 1–3 of the Mirage replay, a
few items; in web/ because the image's frontend build sees only web/), is what the
tests use, backend and frontend (`web/src/test/preview.ts`). Regenerate it with
`.venv/bin/python tests/fixtures/make_preview_sample.py` (no network).

## Building it

`eb preview build` (`src/exiledbroker/preview/build.py`; defaults: `-l Allflame --days
1,3,5,7 --default-day 5 --next-day 10`) runs locally, where `data/` has the league's
pages, and makes **no requests**: its client refuses every one, so a page missing from
disk stops the build (and the last snapshot stands).

- It replays the league into a throwaway DuckDB beside the research one
  (`data/preview-build.duckdb`, deleted afterwards) with the live loader, as the worker
  would have run at the end of each day (`sync_live(now = launch + day × 24 h)`), and
  stores what the services answered then. A last load to `--next-day` gives the
  reveal's documents (`next/…`, `d{day}/recap-next`).
- What the services read besides the league's hours is copied from the research
  database, **rewound**: the Launch history and Price check's per-league paths without
  the replayed league or any later one, then the picks and the medians rebuilt from the
  rest, so the preview never knows what happened next. The reference data (names, core
  pool, card tiers) is today's, and the fitted constants (Price check's bands, the sell
  helper's) stay as fitted: a few numbers across every league.
- The snapshot replaces `preview_snapshot` in the research database in one
  transaction; `version` is the build time plus a hash of the documents.
- `eb site seed` copies the table to the site (it's one of `site.REPLACED_TABLES`,
  replaced whole), and the pipeline's backup copies it to Supabase once per build
  (its stamp: the document count and build time).

## Serving

- `GET /api/preview/{key}` (`api/routes/preview.py`) sends a stored document as it is:
  404 unless the snapshot holds the key (the key list is read once per data version,
  so a miss costs no query). Documents are cached in memory (`cache.previews`, bounded,
  keyed on the snapshot's version) and sent with `Cache-Control: public, max-age=86400`
  when the request's `v` is the snapshot's version.
- `/api/status` carries `preview` (the manifest) while the preview is on. `EB_PREVIEW`:
  `auto` (default) while a next league is announced (`EB_NEXT_LEAGUE_START`) and has no
  trades yet; `on` whenever a snapshot exists (local development); `off` never.
- The announced league (`upcoming`) works with only a date (`EB_NEXT_LEAGUE_START=2026-11-13`):
  `time_known` is false and `start_at` / `first_data_at` are null. The name
  (`EB_NEXT_LEAGUE`) may be unset: then the league counts as arrived once any league
  launched from the day before that date has trades. The pipeline switches to the new
  league only once both the name and the time are set (`pipeline.pick_league`).

## Frontend

- `lib/preview.ts`: `usePreview()` gives `{on, day, days, setDay, league, hour, version,
  manifest}`; the day is the URL's `day`, else the manifest's default.
- `api/queries.ts` is the one switch: while the preview is on, `useMissed`,
  `usePriceCheck`, `usePriceCheckItem` and `useLaunchPicks` read `/api/preview/d{day}/…`
  keyed on the snapshot's version; `useLeagues()` returns the snapshot's league on the
  chosen day (the pages use it instead of `status.leagues`). The reveal's data:
  `usePreviewItemNext(itemId)` and `usePreviewRecapNext()`.
- The reveal ("what happened next", `components/Reveal.tsx`, `RevealItem.tsx`, `lib/reveal.ts`,
  `lib/revealItem.ts`) sits behind a button and fetches nothing until opened. Price check: the
  typical price (median of 6 hours, in Divines; Chaos for the Divine Orb) 1 and 3 days after
  the day's last hour, against that day's calls (Sell held if it fell, Hold if it didn't),
  and the path to `next_until` greyed past the day. Market recap: a tally of the page's
  trades, and on each card its next hours (paid / didn't / didn't trade), the next hour and
  whether it still paid a day later.
- Usage events for the preview (`api/usage.py` FEATURES, `lib/usage.ts`):
  `trackFeature('preview-day')` when a visitor picks a day, `'preview-reveal'` when they
  open "what happened next", `'preview-cta'` for its call to action, and v2's
  `'portfolio-add'` / `'portfolio-step'` ([usage.md](usage.md#the-preview)).

## Operations

- Switching it on, the environment (`EB_NEXT_LEAGUE_START=2026-11-13` alone on both
  services), what ends it and the spike readiness for the announcement:
  [go-live.md](go-live.md#11-the-preview-and-the-reddit-announcement).
- `eb site smoke` checks the preview while `/api/status` has it: the manifest (the
  same version as status's, cached a day), the default day's documents and one item's,
  and that a missing key is 404. A league announced without a preview is a warning.
- The Reddit posts and the link preview's text: [announcement.md](announcement.md).
