# Roadmap

The longer-term design: what the tool is meant to predict, and the phases not yet built. Current progress is in the [README's Status table](../README.md#status).

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
- **Divination card expected value** for random rewards ([data.md](data.md#divination-cards)). Unique rewards are out, with uniques (2026-10-25).

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

The site will split into a **live trading** section and a **historical** section with preloaded data and graphs. This is being designed; don't build it yet.

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
