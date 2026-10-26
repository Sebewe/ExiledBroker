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
- Usage events reserved for the preview: `feature:preview-day`, `feature:preview-reveal`,
  `feature:preview-cta`, `feature:portfolio-add`, `feature:portfolio-step`.
