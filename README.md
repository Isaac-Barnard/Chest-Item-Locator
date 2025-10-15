Here is bad schema


-- connect to postgres, then:
CREATE DATABASE minecraft_world;
\c minecraft_world

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";  -- optional
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- optional

CREATE TABLE IF NOT EXISTS storages (
  storage_id      BIGSERIAL PRIMARY KEY,
  world_name      TEXT,
  region_file     TEXT,
  chunk_index     INT,
  entity_id       TEXT,
  x               INT,
  y               INT,
  z               INT,
  updated_at      TIMESTAMPTZ DEFAULT now(),
  raw_nbt         JSONB,
  UNIQUE (x, y, z)
);

CREATE TABLE IF NOT EXISTS storage_items (
  id              BIGSERIAL PRIMARY KEY,
  storage_id      BIGINT REFERENCES storages(storage_id) ON DELETE CASCADE,
  slot            INT,
  item_id         TEXT,
  count           INT,
  display_name    TEXT,
  raw_item_nbt    JSONB
);

CREATE INDEX IF NOT EXISTS idx_storages_xyz ON storages(x, y, z);
CREATE INDEX IF NOT EXISTS idx_items_itemid ON storage_items(item_id);
CREATE INDEX IF NOT EXISTS idx_items_storageid ON storage_items(storage_id);
