# Roadmap

The longer-term design: what the tool is meant to predict, and the phases not yet built. Current progress and the next steps are below; how the system is built is in [architecture.md](architecture.md).

## Status

| Phase | Goal | State |
|---|---|---|
| 0 | Scaffolding: package, CLI, schema, config, service layer | ✅ Done |
| 1 | Historical ingest: daily poe.ninja dumps + hourly GGG exchange, league calendar, price mappings, core pool, divination cards | ✅ All 32 challenge leagues daily; hourly for the four exchange-era leagues and the current league (Allflame) |
| 2 | Exploration: recurring launch-week patterns (`analysis/`), loops and card turn-ins (now on the Market recap) | ✅ Run across all five exchange-era leagues: what repeats is [finding 10](findings.md#10-what-repeats-across-the-five-exchange-era-leagues) |
| 3 | Patch corpus: scraper, extractor, review tool | ⬜ |
| 4 | Baseline + backtest: first honest accuracy numbers | 🟨 The site's tools backtested at fair and harsh prices: Launch picks pay, hourly tools at best break even ([finding 4](findings.md#4-backtest-the-launch-picks-pay-the-hourly-tools-at-best-break-even), the Backtest page) |
| 5 | Signals: "farm X", "buy Y on day 2, sell day 6" | 🟨 The Farming page's mechanic ranking is retired (2026-10-25); the Price check page replaces it: one item's price in Chaos and Divines, a sell-or-hold verdict if one beats "no change", the stack seller and the best hour to sell ([findings 6–8](findings.md), [price-check.md](price-check.md)). Built end to end (data, API, page, seed, backup, the pipeline adds each finished league's paths); the 375 px check is left |
| 6 | Live mode: hourly ingest of the running league, live arbitrage view, later drift alerts | 🟨 Live feed and Market recap page built; alerts not started (the poe.ninja poller is dropped with uniques, 2026-10-25) |
| 7 | Hosted site: React on the JSON API, all on Railway (web, Postgres, hourly pipeline), with an off-site backup on Supabase | 🟨 Built and simulated locally with Railway's billing ($2.7–3.7 a month of usage at 10–100 daily visitors, ~$4.9 estimated at 1000, inside the $5 Hobby fee); the backup is seeded; the Cloudflare fallback Worker (`deploy/cloudflare/`) and the pipeline's failure alert (`EB_HEALTHCHECK_URL`) are built; not deployed |

Legend: ⬜ not started · 🟨 in progress · ✅ done. Phases 1–2 alone are useful: knowing which categories reliably spike in the first week is already an edge.

## Next steps

The next league launches in about a month. Before then:

- **Go live on Railway** (waiting on Railway reopening signups): the checklist is [go-live.md](go-live.md). The code side is done (Postgres-only server, rehearsed league switch, fallback Worker, failure alert); what's left is account setup: the Railway project, the healthchecks.io check, an uptime monitor, Cloudflare in front, then the seed and catch-up test. Each deploy is checked with `eb site smoke <url>`; launch day and rollback are sections 9 and 10, and Fly.io / Render are compared in [hosting.md](hosting.md#if-railway-stays-closed-flyio-or-render) in case Railway stays closed.
- **Register the new league** once its name and date are announced (`eb exchange sync -l "<Name>" --start <date>`), so the site shows "waiting for the first trades" from launch.

After that:
- **Phase 2 again on the next league** once its fortnight is complete (~2026-11-27): the first out-of-sample check of [finding 10](findings.md).
- **Site split** into Trade and Research sections: Research is built (journal, How the tools work, Backtest, Multi-layered conversions, About); next are the Trade pages' simplification and the History graphs (plan under [Planned site structure](#planned-site-structure)).


## The goal

Each new league starts with an empty economy, so nothing can be bought before launch. The edge is **predicting how prices move over the first ~14 days**, from what happened in past leagues plus what this patch changes:

1. **Baseline:** how does this item's price usually move from day 0 to day 14?
2. **Patch effect:** how do this patch's buffs, nerfs, new mechanics and drop changes shift that path?
3. **Action:** what to farm, what to buy cheap on days 1–3 and sell on days 5–10, and how confident the tool is.

Then **live tracking** during launch week, flagging items that drift from their predicted path.

```
patch notes ──► parse ──► LLM extraction ──► reviewed changes ─┐
                                                               ├─► features ─► models ─► signals ─► site
price history ──► ingest ──► normalize (day offset, renames) ──┘                  ▲
live prices ───────────────────────────────────────────────────────────────────┘ (live comparison)
```

## Phase 3: patch notes

1. Split the notes into sections and lines.
2. An LLM turns each line into a `PatchChange` with a fixed set of change types (pydantic schema).
3. Match the change to items directly ("Mageblood now…") and indirectly: a buffed skill raises demand for the currency and cards its builds need.
4. **Review extractions by hand.** A few patches a year at ~300 lines each is realistic, and it produces labelled data.

## Phase 4–5: models, backtest, signals

There are only about 15–25 leagues of usable data, so start simple:

1. **Baseline curves:** the median day 0–14 path per item and category, scaled to the day-1 price (the launch curves in `analysis/` are the start of this).
2. **Analog matching:** find past items with a similar change (e.g. "mechanic buffed, magnitude 2, more drops") and apply their observed lift.
3. **Learned model (later):** gradient boosting on curve, change and demand features, only once the backtest shows it beats step 2.
4. **Backtest everything:** hold out each league, give the model only its patch notes, and score its day 1/3/7/14 predictions. Built early, because it's what says whether anything works.

Signals then become a ranked list: "farm X", "buy Y on day 2, sell on day 6".

## Phase 6: live, still to do

- **Prediction alerts** once there are predictions to drift from.
- **Divination card expected value** for random rewards: researched ([finding 12](findings.md#12-cards-with-random-rewards-two-delirium-orb-cards-beat-their-floor-at-typical-prices-nothing-survives-harsh-prices-in-the-launch-fortnight)); the user chose to show them on the Market recap's card turn-ins at their floor (2026-10-26, [decisions](decisions.md)); built the same day (`card_reward_pool`, the "worst roll" note).

## Planned modules

```
ingest/patch_notes.py       # scrape raw text → store
normalize/entities.py       # name resolution, renames, variants
patchnotes/                 # taxonomy.py (change types), extractor.py (LLM), review.py
features/                   # curve shape, change impact, demand proxies
models/                     # baseline.py, impact.py, backtest.py (leave-one-league-out)
signals/                    # ranking, buy/sell windows, risk
```

## Planned data model

```
ItemAlias(alias, item_id, valid_from_league)     -- renames and reworks
PatchNote(id, league_id, version, published_at, url, raw_text)
PatchChange(id, patch_note_id, section, raw_line,
            entity_type,   -- skill_gem | unique | mechanic | currency | drop_rate | crafting ...
            entity_ref, change_type, direction (+/-), magnitude (0-3),
            confidence, extracted_by, reviewed)
PatchChangeItem(patch_change_id, item_id, relation)  -- direct | ingredient | build_dependency
Prediction(run_id, league_id, item_id, horizon_day, p10, p50, p90, rationale)
```

## Planned site structure

The site is splitting into a **Trade** section and a **Research** section with preloaded data and graphs. Research is built (2026-10-26): `/research` is a journal of the findings, with How the tools work, the Backtest, Multi-layered conversions and About under it. Still to come, as the user approves: simplifying the Trade pages (a summary line, hiding empty sections, the header search) and the History graphs, which need their own precomputed views.

## Add-ons

- **Flip tracker.** Track exchange pairs with high volume and a decent spread and surface what's worth flipping. The hourly digests already carry volume and low/high ratios, so flip margins can be backtested on past launches first. It advises the player; automating trades is against GGG's terms.
- **Build popularity.** Main skills and ascendancies as a demand signal. ⚠️ poe.ninja's builds/profiles API is internal and off-limits, and their builds pages are rendered from it, so scraping them is effectively using it. Ask poe.ninja first (they're on Discord), or use another source: GGG's ladder API gives class/ascendancy but needs a registered OAuth app.

## Risks

- **Thin or manipulated markets:** drop or down-weight thin items. History has only Low/Medium/High confidence; live data will give real counts.
- **Structural changes** (the currency exchange, new crafting systems) break past patterns. Tag leagues with them so models can account for them.
- **Renames and reworks:** the planned `ItemAlias` table.
- **Survivorship bias:** poe.ninja only tracks items that are listed.
- **Table size:** ~150 bytes a row in DuckDB, mostly the text key. All challenge leagues are roughly 10M rows. Hosting only the running league keeps Postgres small ([hosting.md](hosting.md), issue 8).
- **Data quality:** RePoE names and GGG's volume figures, see [data.md](data.md#ggg-hourly-exchange).
