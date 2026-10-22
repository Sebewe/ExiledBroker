-- Core schema. Statements are idempotent so `eb init-db` can be re-run safely.
-- Keep to SQL that runs on both DuckDB (local) and Postgres (Supabase, hosted).

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

-- Cross-market: every item-hour that traded against both Chaos and Divine, with the
-- hour's Divine rate. Each leg has its volume-weighted price, units traded, and the
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
