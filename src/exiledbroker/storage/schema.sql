-- Core schema. Statements are idempotent so `eb init-db` can be re-run safely.

CREATE TABLE IF NOT EXISTS league (
    id          VARCHAR PRIMARY KEY,           -- e.g. 'poe1-settlers'
    game        VARCHAR NOT NULL,              -- 'poe1' | 'poe2'
    name        VARCHAR NOT NULL,
    version     VARCHAR,                       -- patch version, e.g. '3.25'
    start_at    TIMESTAMP NOT NULL,
    end_at      TIMESTAMP,
    mechanic    VARCHAR                        -- headline league mechanic
);

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
    day_offset    DOUBLE NOT NULL,             -- days since league start
    chaos_value   DOUBLE,
    divine_value  DOUBLE,
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
    confidence    DOUBLE,
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
    p10         DOUBLE,
    p50         DOUBLE,
    p90         DOUBLE,
    rationale   VARCHAR,
    created_at  TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (run_id, league_id, item_id, horizon_day)
);
