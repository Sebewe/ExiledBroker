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
| `next/price-check/{item_id}` | `PreviewItemNext` | the item's series from launch to day 10, for the reveal |
| `game/{n}` | `PreviewGameHour` | the trading game's hour `n` (hours since launch, from the first day's end to `next_until`): the recap then, the orders a player can take and the flip items' prices ([below](#the-trading-game)) |

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
  stores what the services answered then. In between, it loads one hour at a time and
  stores each hour's recap for the trading game. A last load to `--next-day` gives the
  reveal's documents (`next/…`) and the game's orders (`game/{n}`). The hourly loads
  make the build longer (some 200 loads from day 1 to day 10); it still makes no request.
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
- `components/Preview.tsx`: the header's pill, the strip under it with the day picker, and
  the first visit's notice (`PreviewWelcome`): a modal over the dimmed page saying the site
  is in preview mode and which league, day and hour it shows, until "Got it" (or Escape).
  Accepting stores the snapshot's league and the time in localStorage (`eb-preview-seen`,
  `{league, at}`), so it comes back 4 hours later (the user, 2026-10-27; decided once per
  page load), at once for another league's preview, never when preview is off.
- `components/Tour.tsx` (a lazy chunk; `lib/tour.ts` decides when): the trading game's
  first-visit tour, three small pointers at Trade this hour, Next hour and Portfolio
  (`data-tour` marks). It waits until the welcome is closed and the page shows a trade,
  then never shows again once finished or skipped (`eb-tour-done`; the user, 2026-10-27).
- `api/queries.ts` is the one switch: while the preview is on, `useMissed`,
  `usePriceCheck`, `usePriceCheckItem` and `useLaunchPicks` read `/api/preview/d{day}/…`
  keyed on the snapshot's version; `useLeagues()` returns the snapshot's league on the
  chosen day (the pages use it instead of `status.leagues`). While a trading game runs,
  `useMissed` reads the game's hour instead (`useGameHour(n)`, `game/{n}`). The reveal's
  data: `usePreviewItemNext(itemId)`.
- The reveal ("what happened next", `components/Reveal.tsx`, `RevealItem.tsx`,
  `lib/revealItem.ts`, Price check only) sits behind a button in its box, right under the
  price chart, and fetches nothing until opened: the typical price (median of 6 hours, in
  Divines; Chaos for the Divine Orb) 1 and 3 days after the day's last hour, against that
  day's calls (Sell held if it fell, Hold if it didn't), shown in the box. What came next is
  drawn dotted on the item's own chart, in each line's colour, over the 3 days past the
  day's last hour (the user, 2026-10-28: no second chart, nothing jumps). In the preview the
  chart's axis always keeps those 3 days, so opening the reveal only adds the lines; the
  series carry ids and the chart merges them in (`Chart`'s `morph`). The day's outlook
  band stays (the item chart's `outlookBand` from that day's snapshot, never recomputed
  from what came next; the user, 2026-10-27: to see how the prediction held up). The recap
  has the trading game instead.
- The trading game ([below](#the-trading-game)): "Trade this hour" on the recap's loops,
  cards and flips, and a bar fixed to the bottom of the recap with the player's Divines
  and "Next hour" (`components/Game.tsx`, a lazy chunk; z-20, under popups, and the body
  gets `has-game-bar` padding while it's shown). The Portfolio page (`/portfolio`,
  `pages/Portfolio.tsx`, in the menu only while the preview is on) lists the open trades
  (a held flip's listing can be changed, or it can be sold now) and the history of closed
  ones with what each made or lost, and starts over.
- Usage events for the preview (`api/usage.py` FEATURES, `lib/usage.ts`):
  `trackFeature('preview-day')` when a visitor picks a day, `'preview-reveal'` when they
  open "what happened next", `'preview-cta'` for its call to action, and the trading
  game's `'game-trade'` / `'game-step'` ([usage.md](usage.md#the-preview)).

### The trading game

The user's design (2026-10-27): players start with 10 Divines and 200 Chaos at the end of
the chosen day and play the rewound league hour by hour, trading only what the Market recap lists,
so the only way up is trading. The rules are `lib/game.ts`; the state is `eb-game` in
localStorage (in memory where storage is blocked): no accounts, nothing sent.

- **The wallet** (the user, 2026-10-27): Divines and Chaos kept apart, 10 div and 200c to
  start. Trades are paid in Chaos and pay out in Chaos. Divines exchange at the hour's
  average Divine price (`divine_chaos`), whole Divines at a time: by the player (the bar's
  Exchange, either way) or on their own when a trade needs more Chaos than the wallet has.
  The total is shown in Divines at the hour's price and the gain is measured against the
  start (10 div + 200c) at that same price. The bar (with "Next hour") is on the recap
  and the Portfolio page, which also shows each open trade's buy price and a "Reset
  game" button. A game stored before this (`v` not 3) starts over.
- **Whole purchases at the real price** (the user, 2026-10-27: "you can't put 2 div in
  something that has a 3 div buy-in"). A player buys a number of a trade's smallest whole
  purchases: a loop's or card's order `lot` (Chaos for the smallest whole lot at its bid,
  `sell_lot` units of a loop, enough whole sets for a card), a flip's whole bid
  (`bid_lot` items for `bid_total`). The form says what one costs in Chaos and how many the
  wallet can pay (exchanging Divines, 10 Divines' worth a trade at most); a trade whose
  purchase costs more than that can't be placed. Orders fill in whole purchases too.
- **Hours.** `game/{n}` is the site `n` hours after launch (its latest hour is
  `launch + n − 1 h`), for every `n` from the first day's end to `next_until`
  (`manifest.game`: `first`, `last`). A game starts at the chosen day's end; while it runs,
  the recap shows its hour (the strip says so and hides the day picker there). "Next hour"
  loads one document (cached a day by the browser and Cloudflare under the snapshot's
  version); a full game from day 1 to day 10 is about 216 requests, no database read.
- **Loops and card turn-ins.** Each hour's document carries the recap's own order for each
  (`preview/build.game_hours`), filled by the Backtest's rules (`loop_order_fills` /
  `card_order_fills`, a fill when a trade went past the order, at most a tenth of what
  traded and 10 Divines an order): `filled` (null: no order, it didn't pay from the bid),
  `spent` and `pnl` (Chaos) and `settle_at` (the hour it sold). A player's purchases fill up to
  `spent` (whole `lot`s), the rest comes back the next hour, and what filled earns `pnl / spent` and is
  tied up until `settle_at`. A sale not known by `next_until` stays open at what it cost.
  Nothing sells by itself at a loss (the user, 2026-10-27: no automatic sale, flag it
  "Dump now" instead): where the sale never filled (`unsold`: the Backtest gave up after
  `SELL_WITHIN` and counted it lost), the player is left holding `units` of `hold` a
  purchase (the loop's item, the card's reward), priced each hour in `prices` (a
  loop's item from its Chaos market, `cross_market_hour`, since the hourly price rows keep
  only price-mapping items; a card's reward from the Backtest's hourly prices), flagged **Dump now**, with "Sell now" at the hour's lowest
  trade; they can also hold on. Held like this, the items are valued at what Sell now gets
  (the hour's lowest trade), since in a thin market the average shows a profit dumping
  doesn't get.
  Random-reward cards aren't offered (the Backtest can't price them).
- **Flips** are held positions, played in the browser from each hour's Chaos prices (low,
  average, high, items traded) of every item the game lists to flip. The bid (the recap's)
  fills the next hour if a trade went under it, up to a tenth of the hour's trades and 10
  Divines; then the items are listed from the hour after at the recap's ask, cut by its
  `cut` each hour, unless the player sets a price, and sell when a trade goes over the
  listing, a tenth of the hour's trades at most. "Sell now" takes the hour's lowest trade.
  A held flip is flagged **Dump now** once it has been listed 6 hours (`DUMP_AFTER`)
  without a sale and its average price is under what it cost.
  A held item counts at its latest average price.
- One order a trade an hour (the market's share can't be taken twice).

## Operations

- Switching it on, the environment (`EB_NEXT_LEAGUE_START=2026-11-13` alone on both
  services), what ends it and the spike readiness for the announcement:
  [go-live.md](go-live.md#11-the-preview-and-the-reddit-announcement).
- `eb site smoke` checks the preview while `/api/status` has it: the manifest (the
  same version as status's, cached a day), the default day's documents and one item's,
  and that a missing key is 404. A league announced without a preview is a warning.
- The Reddit posts and the link preview's text: [announcement.md](announcement.md).
