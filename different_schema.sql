CREATE DATABASE minecraft_world;

CREATE TABLE IF NOT EXISTS storages (
    storage_id      BIGSERIAL PRIMARY KEY,
    region_file     TEXT,
    chunk_index     INT,
    entity_id       TEXT,
    x               INT,
    y               INT,
    z               INT,
    nation_company  TEXT,
    irrelevant      BOOLEAN,
    UNIQUE (x, y, z)
);

CREATE TABLE IF NOT EXISTS storage_inventory (
    id              BIGSERIAL PRIMARY KEY,
    storage_id      BIGINT REFERENCES storages(storage_id) ON DELETE CASCADE,
    slot            INT,
    item_id         TEXT,
    count           INT,
    display_name    TEXT
);

CREATE INDEX IF NOT EXISTS idx_storages_xyz ON storages(x, y, z);
CREATE INDEX IF NOT EXISTS idx_storage_inventory_itemid ON storage_inventory(item_id);
CREATE INDEX IF NOT EXISTS idx_storage_inventory_storageid ON storage_inventory(storage_id);