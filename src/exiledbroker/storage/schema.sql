-- Core schema. Statements are idempotent so `eb init-db` can be re-run safely.
-- Keep to SQL that runs on both DuckDB (local) and Postgres (Railway, hosted).

CREATE TABLE IF NOT EXISTS league (
    id          VARCHAR PRIMARY KEY,           -- e.g. 'poe1-settlers'
    game        VARCHAR NOT NULL,              -- 'poe1' | 'poe2'
    name        VARCHAR NOT NULL,
    version     VARCHAR,                       -- patch version, e.g. '3.25'
    start_at    TIMESTAMP NOT NULL,
    end_at      TIMESTAMP,
    mechanic    VARCHAR                        -- headline league mechanic
);

-- Added in phase 1. ADD COLUMN IF NOT EXISTS keeps older local databases working.
ALTER TABLE league ADD COLUMN IF NOT EXISTS kind VARCHAR;       -- challenge | ruthless | event
ALTER TABLE league ADD COLUMN IF NOT EXISTS dump_name VARCHAR;  -- name used by poe.ninja dumps

CREATE TABLE IF NOT EXISTS item (
    id             VARCHAR PRIMARY KEY,
    game           VARCHAR NOT NULL,
    canonical_name VARCHAR NOT NULL,
    category       VARCHAR NOT NULL,           -- currency | unique | gem | fragment | ...
    base_type      VARCHAR,
    variant        VARCHAR,
    links          INTEGER,
    gem_level      INTEGER,
    corrupted      BOOLEAN
);

CREATE TABLE IF NOT EXISTS item_alias (
    alias             VARCHAR NOT NULL,
    item_id           VARCHAR NOT NULL REFERENCES item (id),
    valid_from_league VARCHAR REFERENCES league (id),
    PRIMARY KEY (alias, item_id)
);

CREATE TABLE IF NOT EXISTS price_observation (
    item_id       VARCHAR NOT NULL REFERENCES item (id),
    league_id     VARCHAR NOT NULL REFERENCES league (id),
    observed_at   TIMESTAMP NOT NULL,
    day_offset    DOUBLE PRECISION NOT NULL,             -- days since league start
    chaos_value   DOUBLE PRECISION,
    divine_value  DOUBLE PRECISION,
    listing_count INTEGER,
    source        VARCHAR NOT NULL,            -- 'poe.ninja-dump' | 'poe.ninja-live' | ...
    PRIMARY KEY (item_id, league_id, observed_at, source)
);

CREATE TABLE IF NOT EXISTS patch_note (
    id           VARCHAR PRIMARY KEY,
    league_id    VARCHAR NOT NULL REFERENCES league (id),
    version      VARCHAR,
    published_at TIMESTAMP,
    url          VARCHAR,
    raw_text     VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS patch_change (
    id            VARCHAR PRIMARY KEY,
    patch_note_id VARCHAR NOT NULL REFERENCES patch_note (id),
    section       VARCHAR,
    raw_line      VARCHAR NOT NULL,
    entity_type   VARCHAR,                     -- skill_gem | unique | mechanic | currency | ...
    entity_ref    VARCHAR,
    change_type   VARCHAR,
    direction     SMALLINT,                    -- -1 nerf, 0 neutral, +1 buff
    magnitude     SMALLINT,                    -- 0-3
    confidence    DOUBLE PRECISION,
    extracted_by  VARCHAR,
    reviewed      BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS patch_change_item (
    patch_change_id VARCHAR NOT NULL REFERENCES patch_change (id),
    item_id         VARCHAR NOT NULL REFERENCES item (id),
    relation        VARCHAR NOT NULL,          -- direct | ingredient | build_dependency
    PRIMARY KEY (patch_change_id, item_id, relation)
);

CREATE TABLE IF NOT EXISTS prediction (
    run_id      VARCHAR NOT NULL,
    league_id   VARCHAR NOT NULL REFERENCES league (id),
    item_id     VARCHAR NOT NULL REFERENCES item (id),
    horizon_day INTEGER NOT NULL,
    p10         DOUBLE PRECISION,
    p50         DOUBLE PRECISION,
    p90         DOUBLE PRECISION,
    rationale   VARCHAR,
    created_at  TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (run_id, league_id, item_id, horizon_day)
);

-- Added in phase 1 (dump loader).
ALTER TABLE item ADD COLUMN IF NOT EXISTS ninja_id BIGINT;            -- poe.ninja line id, stable across leagues
ALTER TABLE item ADD COLUMN IF NOT EXISTS gem_quality INTEGER;
ALTER TABLE price_observation ADD COLUMN IF NOT EXISTS confidence VARCHAR;      -- Low | Medium | High
ALTER TABLE price_observation ADD COLUMN IF NOT EXISTS chaos_ask DOUBLE PRECISION; -- chaos paid for one unit
ALTER TABLE price_observation ADD COLUMN IF NOT EXISTS chaos_bid DOUBLE PRECISION; -- chaos received for one unit

-- One row per (league, source) load, so re-running a load is a no-op.
CREATE TABLE IF NOT EXISTS ingest_load (
    league_id   VARCHAR NOT NULL REFERENCES league (id),
    source      VARCHAR NOT NULL,
    fingerprint VARCHAR NOT NULL,
    item_count  INTEGER,
    row_count   BIGINT,
    loaded_at   TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (league_id, source)
);

-- Added in phase 1 (hourly currency exchange).
ALTER TABLE league ADD COLUMN IF NOT EXISTS launched_at TIMESTAMP;   -- first hour seen on the exchange (UTC)
ALTER TABLE item ADD COLUMN IF NOT EXISTS metadata_id VARCHAR;       -- GGG metadata path, e.g. Metadata/Items/Currency/CurrencyModValues
ALTER TABLE price_observation ADD COLUMN IF NOT EXISTS volume DOUBLE PRECISION;       -- units traded in the period
ALTER TABLE price_observation ADD COLUMN IF NOT EXISTS chaos_volume DOUBLE PRECISION; -- chaos-equivalent traded
ALTER TABLE price_observation ADD COLUMN IF NOT EXISTS chaos_low DOUBLE PRECISION;    -- lowest traded price in the period
ALTER TABLE price_observation ADD COLUMN IF NOT EXISTS chaos_high DOUBLE PRECISION;   -- highest traded price in the period

-- Curated price mappings: which items belong to which tracked group.
CREATE TABLE IF NOT EXISTS tracked_item (
    item_id     VARCHAR NOT NULL REFERENCES item (id),
    group_id    VARCHAR NOT NULL,            -- chaos | divine | alchemy | mirror | essence | scarab
    group_label VARCHAR NOT NULL,
    sort_order  INTEGER NOT NULL,
    PRIMARY KEY (item_id, group_id)
);

-- Leagues followed on the hourly exchange, including ones with no data yet (a new
-- league is registered before its first hour is published).
ALTER TABLE league ADD COLUMN IF NOT EXISTS exchange_tracked BOOLEAN DEFAULT FALSE;

-- Divination cards: what a full set turns into, and whether we follow the card.
-- Rebuilt from RePoE (set size, reward) and NeverSink's filter (tier) on each load.
CREATE TABLE IF NOT EXISTS divination_card (
    item_id         VARCHAR PRIMARY KEY,     -- currency:<slug>, same id as its prices
    name            VARCHAR NOT NULL,
    stack_size      INTEGER,                 -- cards in a full set
    reward_kind     VARCHAR,                 -- currency | divination | unique | gem | rare | magic | normal | other
    reward_name     VARCHAR,                 -- e.g. 'Exalted Orb', 'Headhunter'
    reward_quantity INTEGER,                 -- e.g. 10 for '10x Exalted Orb'
    reward_item_id  VARCHAR,                 -- set when the reward is priced on the exchange
    reward_text     VARCHAR,                 -- raw reward text, incl. extras like 'Corrupted'
    filter_tier     VARCHAR,                 -- NeverSink tier: t1 ... t5 (hidden), null if unlisted
    followed        BOOLEAN NOT NULL         -- shown by the filter and in the core pool
);
-- Fixed reward = one specific item; random rewards ("5x Currency") need an expected value.
-- Only decided for currency and card rewards for now; null for uniques, gems, etc.
ALTER TABLE divination_card ADD COLUMN IF NOT EXISTS reward_fixed BOOLEAN;

-- What a random card reward can roll ("10x Delirium Orb"): config/card_rewards.toml's
-- pools, resolved against item names on each load (normalize/card_rewards.py). The
-- Market recap prices these cards at the cheapest item the reward can roll.
CREATE TABLE IF NOT EXISTS card_reward_pool (
    reward_name VARCHAR NOT NULL,            -- divination_card.reward_name
    item_id     VARCHAR NOT NULL,            -- an item it can roll
    PRIMARY KEY (reward_name, item_id)
);

-- Cross-market: every item-hour that traded against Chaos, with the Divine leg and the
-- hour's Divine rate when it also traded against Divine (else null; loops need both). Each leg has its volume-weighted price, units traded, and the
-- lowest/highest traded price that hour, all in the leg's reference currency.
CREATE TABLE IF NOT EXISTS cross_market_hour (
    league_id        VARCHAR NOT NULL REFERENCES league (id),
    item_id          VARCHAR NOT NULL REFERENCES item (id),
    observed_at      TIMESTAMP NOT NULL,
    day_offset       DOUBLE PRECISION,
    chaos_price      DOUBLE PRECISION,   -- chaos per item, X/Chaos market
    chaos_volume     DOUBLE PRECISION,   -- items traded in X/Chaos
    chaos_low        DOUBLE PRECISION,
    chaos_high       DOUBLE PRECISION,
    divine_price     DOUBLE PRECISION,   -- divines per item, X/Divine market
    divine_volume    DOUBLE PRECISION,   -- items traded in X/Divine
    divine_low       DOUBLE PRECISION,
    divine_high      DOUBLE PRECISION,
    divine_rate      DOUBLE PRECISION,   -- chaos per divine, same hour (no carry-forward)
    divine_rate_low  DOUBLE PRECISION,
    divine_rate_high DOUBLE PRECISION,
    PRIMARY KEY (league_id, item_id, observed_at)
);

-- Which exchange hours each league has loaded (including hours where nothing traded),
-- so updates insert only new hours and remove only hours that left the window.
CREATE TABLE IF NOT EXISTS exchange_hour_loaded (
    league_id VARCHAR NOT NULL REFERENCES league (id),
    hour      TIMESTAMP NOT NULL,
    PRIMARY KEY (league_id, hour)
);

-- Access paths: pages filter by league + source + time, but the primary keys start
-- with item id. Without these, Postgres would scan whole tables (cost issue #3).
-- In DuckDB they're cheap (no measurable file growth; 21 ms → 1 ms on Allflame).
CREATE INDEX IF NOT EXISTS price_obs_league_time ON price_observation (league_id, source, observed_at);
CREATE INDEX IF NOT EXISTS cross_market_league_time ON cross_market_hour (league_id, observed_at);

-- Reference data the worker needs on every run (RePoE item names, the core-pool lists,
-- the loot filter's card tiers). Kept in the database, the worker's only persistent
-- store, so a wiped disk doesn't mean re-downloading it every hour (cost issue #6).
CREATE TABLE IF NOT EXISTS reference_data (
    key        VARCHAR PRIMARY KEY,   -- e.g. 'repoe/base_items', 'core_pool/type/Currency'
    fetched_at TIMESTAMP NOT NULL,
    content    VARCHAR NOT NULL       -- JSON
);
-- Conditional requests: a check sends these back and gets "304 Not Modified" (no body)
-- when nothing changed, so reference data we already have is never downloaded again.
ALTER TABLE reference_data ADD COLUMN IF NOT EXISTS source_url VARCHAR;
ALTER TABLE reference_data ADD COLUMN IF NOT EXISTS etag VARCHAR;
ALTER TABLE reference_data ADD COLUMN IF NOT EXISTS last_modified VARCHAR;
ALTER TABLE reference_data ADD COLUMN IF NOT EXISTS checked_at TIMESTAMP;  -- last check, changed or not

-- One row per live update (`eb live sync` / `watch`): what it fetched, what it wrote,
-- how long it took and whether it failed, so the worker's cost can be watched over
-- time. Ops data, not read by the site; rows older than 90 days are deleted.
CREATE TABLE IF NOT EXISTS ingest_run (
    league_id      VARCHAR NOT NULL,
    started_at     TIMESTAMP NOT NULL,
    seconds        DOUBLE PRECISION,
    state          VARCHAR NOT NULL,   -- LiveStatus.state, or 'failed'
    latest_hour    TIMESTAMP,
    pages_fetched  INTEGER,            -- new exchange pages
    requests       INTEGER,            -- every HTTP request, reference checks included
    bytes_received BIGINT,
    not_modified   INTEGER,            -- reference checks answered 304
    hours_added    INTEGER,
    hours_removed  INTEGER,
    rows_added     BIGINT,
    rows_total     BIGINT,             -- the league's hourly price rows afterwards
    error          VARCHAR,
    PRIMARY KEY (league_id, started_at)
);

-- Launch picks (the Launch market page): what to buy in each early-league window, ranked
-- from past leagues' hourly prices by `eb launch picks` on the research database and
-- copied to the site by `eb site seed`. Past leagues don't change, so this is rebuilt
-- only when a league's launch fortnight completes. A rebuild replaces every row.
CREATE TABLE IF NOT EXISTS launch_window (
    window_id     VARCHAR PRIMARY KEY,  -- 'day1' | 'days2_4' | 'days5_10'
    first_day     INTEGER NOT NULL,     -- 1-based launch days the window covers
    last_day      INTEGER NOT NULL,
    sell_first    INTEGER NOT NULL,     -- the days the picks are sold in
    sell_last     INTEGER NOT NULL,
    leagues       VARCHAR NOT NULL,     -- the reference leagues, newest first, comma-separated
    chaos_growth  DOUBLE PRECISION,     -- Chaos held from the window to the sale, in Divines
    typical_growth DOUBLE PRECISION,    -- the median affordable item's, in Divines
    candidates    INTEGER NOT NULL,     -- items that passed the filters
    built_at      TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS launch_pick (
    window_id  VARCHAR NOT NULL,
    item_id    VARCHAR NOT NULL,
    rank       INTEGER NOT NULL,
    name       VARCHAR NOT NULL,
    group_id   VARCHAR NOT NULL,
    score      DOUBLE PRECISION NOT NULL,
    growth     DOUBLE PRECISION NOT NULL,  -- typical sale/buy multiple in Divines (recency-weighted)
    worst      DOUBLE PRECISION NOT NULL,  -- the worst league's multiple
    rose       INTEGER NOT NULL,           -- leagues where it beat holding Divines
    traded     INTEGER NOT NULL,           -- leagues it traded in, in the window and the sale
    buy_divine DOUBLE PRECISION NOT NULL,  -- typical unit price in the window, in Divines
    liquidity  DOUBLE PRECISION NOT NULL,  -- Divines traded a day (the thinner of buy and sale)
    PRIMARY KEY (window_id, item_id)
);
CREATE TABLE IF NOT EXISTS launch_pick_league (
    window_id VARCHAR NOT NULL,
    item_id   VARCHAR NOT NULL,
    league    VARCHAR NOT NULL,
    growth    DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (window_id, item_id, league)
);

-- Raw exchange pages kept in the database (EB_EXCHANGE_PAGES=database, the hosted
-- pipeline): gzipped JSON, one row per hour, only the live window's (older ones are
-- pruned after each load). A loader rebuild re-reads these instead of fetching again.
-- Locally pages are files under data/raw and this table stays empty.
CREATE TABLE IF NOT EXISTS exchange_page (
    hour BIGINT PRIMARY KEY,  -- unix time of the hour
    body BYTEA NOT NULL
);

-- What the Launch picks are ranked from: per finished league, item and window (the
-- buy windows and the sale days, services/launch_picks.WINDOWS / SELL), the median
-- hourly Divine price and the Divines traded. Captured once a league's launch
-- fortnight is over, so the picks never need the hourly history itself.
CREATE TABLE IF NOT EXISTS launch_history (
    league        VARCHAR NOT NULL,
    league_start  TIMESTAMP NOT NULL,
    item_id       VARCHAR NOT NULL,
    window_id     VARCHAR NOT NULL,  -- 'day1' | 'days2_4' | 'days5_10' | 'sell'
    divine        DOUBLE PRECISION NOT NULL,
    divine_volume DOUBLE PRECISION,
    PRIMARY KEY (league, item_id, window_id)
);

-- The Backtest page's report (analysis/backtest.py, `eb backtest run`): one JSON document,
-- built locally from past leagues' hours and copied to the site whole.
CREATE TABLE IF NOT EXISTS backtest_report (
    id        VARCHAR PRIMARY KEY,
    built_at  TIMESTAMP NOT NULL,
    body      VARCHAR NOT NULL
);

-- Retired 2026-10-25 with the Farming page's mechanic ranking (docs/price-check.md, E):
-- its reduced history (~10 MB hosted). Dropped wherever the schema runs (the site's
-- Postgres on the pipeline's next pass, the backup on its next sync, the local copy),
-- a no-op once it's gone; delete this line once every database has run it.
DROP TABLE IF EXISTS item_day_history;

-- The sell helper's constants (services/sell_helper.py, `eb sell-helper build`): finding
-- 6's hour-of-day profiles per phase and finding 7's impact bands, as one JSON document
-- built locally from past leagues (analysis/hours.py needs numpy, which the site doesn't
-- have) and copied to the site whole, like backtest_report. Kept from the Farming page
-- for Price check. Called farming_report until 2026-10-26: renamed in place wherever the
-- schema runs (a no-op once done; delete the ALTER once every database has run it).
ALTER TABLE IF EXISTS farming_report RENAME TO sell_helper_report;
CREATE TABLE IF NOT EXISTS sell_helper_report (
    id        VARCHAR PRIMARY KEY,
    built_at  TIMESTAMP NOT NULL,
    body      VARCHAR NOT NULL
);

-- Price check's verdict (finding 9, services/price_paths.py, `eb price-check build`).
-- Each finished league's own path: per item, its median change in Divines from each
-- half-day bin of the league (bin = hour since launch // 12) over the next 24 hours
-- and 3 days, as JSON lists indexed by bin (null where it had none). Captured once a
-- league's launch fortnight is over (locally, or by the hosted pipeline), so the
-- served paths can be rebuilt without the past leagues' hours.
CREATE TABLE IF NOT EXISTS price_path_league (
    league        VARCHAR NOT NULL,
    league_start  TIMESTAMP,
    item_id       VARCHAR NOT NULL,
    h24           VARCHAR NOT NULL,  -- JSON: log change over 24 hours, by bin
    d3            VARCHAR NOT NULL,  -- JSON: log change over 3 days, by bin
    PRIMARY KEY (league, item_id)
);

-- What the site reads: per item and bin, the median over the captured leagues of each
-- league's path, and how many leagues it rests on (only where at least 2 have it).
CREATE TABLE IF NOT EXISTS price_path (
    item_id     VARCHAR NOT NULL,
    bin         INTEGER NOT NULL,
    h24         DOUBLE PRECISION,
    h24_leagues INTEGER,
    d3          DOUBLE PRECISION,
    d3_leagues  INTEGER,
    PRIMARY KEY (item_id, bin)
);

-- The model's fitted constants per phase, market thickness and horizon: the path's
-- weight and the band's residual quantiles (low, high; log changes). Fitted locally
-- (numpy) by `eb price-check build`; the verdict thresholds are in code
-- (analysis/price_outlook.SHIP).
CREATE TABLE IF NOT EXISTS price_path_constant (
    phase     VARCHAR NOT NULL,
    thick     BOOLEAN NOT NULL,
    horizon   VARCHAR NOT NULL,  -- 'h24' | 'd3'
    weight    DOUBLE PRECISION NOT NULL,
    low       DOUBLE PRECISION,
    high      DOUBLE PRECISION,
    leagues   VARCHAR NOT NULL,  -- the leagues it was fitted on, oldest first
    built_at  TIMESTAMP NOT NULL,
    PRIMARY KEY (phase, thick, horizon)
);

-- Usage counts (api/usage.py): cookie-free, nothing stored in the browser. A visitor is
-- a keyed hash of their IP and User-Agent under a random salt that lives for one period
-- (a calendar month by default); the IP itself is never stored. When a period ends its
-- totals are kept in `usage_period` and its salt and visitor rows are deleted, so what
-- remains can't be linked to anyone, not even by us.
CREATE TABLE IF NOT EXISTS usage_daily (
    day      DATE NOT NULL,
    event    VARCHAR NOT NULL,  -- 'site', 'page:<path>' or 'feature:<name>' (usage.EVENTS)
    views    BIGINT NOT NULL,   -- page views, or times the feature was used
    visitors BIGINT NOT NULL,   -- distinct visitors that day
    PRIMARY KEY (day, event)
);

-- The current period's salt (one row; replaced, never kept, when the period ends).
CREATE TABLE IF NOT EXISTS usage_salt (
    period VARCHAR PRIMARY KEY,  -- '2026-10' (month), '2026-W43' (week) or '2026-10-26'
    salt   VARCHAR NOT NULL
);

-- The current period's visitors: on how many days each was seen (returning: 2 or more).
CREATE TABLE IF NOT EXISTS usage_visitor (
    period   VARCHAR NOT NULL,
    visitor  VARCHAR NOT NULL,  -- truncated HMAC-SHA256(salt, IP + User-Agent)
    last_day DATE NOT NULL,
    days     INTEGER NOT NULL,
    PRIMARY KEY (period, visitor)
);

-- Today's (visitor, event) pairs, so a restart doesn't count a visitor twice in a day.
-- Emptied each day.
CREATE TABLE IF NOT EXISTS usage_seen (
    day     DATE NOT NULL,
    event   VARCHAR NOT NULL,
    visitor VARCHAR NOT NULL,
    PRIMARY KEY (day, event, visitor)
);

-- Each finished period's totals: distinct visitors and how many came back on another day.
CREATE TABLE IF NOT EXISTS usage_period (
    period    VARCHAR PRIMARY KEY,
    visitors  BIGINT NOT NULL,
    returned  BIGINT NOT NULL  -- seen on 2 or more days of the period
);

-- The pre-launch preview's snapshot (docs/preview.md, `eb preview build`): a past
-- league's early days as the site showed them, one gzipped JSON document per key
-- (src/exiledbroker/preview/snapshot.py lists the keys). Built locally, copied to the
-- site by `eb site seed`, served as stored by /api/preview/{key}.
CREATE TABLE IF NOT EXISTS preview_snapshot (
    key       VARCHAR PRIMARY KEY,
    built_at  TIMESTAMP NOT NULL,
    body      BYTEA NOT NULL
);
