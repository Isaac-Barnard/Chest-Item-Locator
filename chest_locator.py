#!/usr/bin/env python3
"""
import_region_storages.py

Scans region/*.mca (next to this script in ./region) and upserts storage block entities
into Postgres DB 'minecraft_world'. Skips chests that only have a LootTable and no Items.
"""

import os, io, struct, zlib, gzip, json
from typing import Any, Dict, List, Tuple
import psycopg2
from psycopg2.extras import Json

# ------------------ Config ------------------
WORLD_NAME = "un_world_test"  # optional tag in DB rows
REGION_DIR = os.path.join(os.path.dirname(__file__), "region")
DB_CONNECT_KW = {
    "dbname": "minecraft_world",
    "user": "un_project_user",           # or your DB user
    "password": "passtheword",   # set this to your Postgres password
    "host": "localhost",
    "port": 5432
}
# Storage entity id prefixes we consider relevant (case-insensitive check)
STORAGE_IDS = {
    "minecraft:chest", "minecraft:trapped_chest", "minecraft:barrel", "minecraft:shulker_box",
    "minecraft:dispenser", "minecraft:dropper", "minecraft:hopper",
    "minecraft:furnace", "minecraft:blast_furnace", "minecraft:smoker",
    # add more if desired
}

# --------------- NBT constants ----------------
TAG_End=0;TAG_Byte=1;TAG_Short=2;TAG_Int=3;TAG_Long=4;TAG_Float=5;TAG_Double=6
TAG_Byte_Array=7;TAG_String=8;TAG_List=9;TAG_Compound=10;TAG_Int_Array=11;TAG_Long_Array=12

# --------------- NBT Reader -------------------
class NBTReader:
    def __init__(self, data: bytes):
        self.buf = io.BytesIO(data)
    def read(self, n:int) -> bytes:
        b = self.buf.read(n)
        if len(b) != n:
            raise EOFError("Unexpected EOF reading NBT")
        return b
    def read_ubyte(self) -> int:
        return struct.unpack(">B", self.read(1))[0]
    def read_byte(self) -> int:
        return struct.unpack(">b", self.read(1))[0]
    def read_short(self) -> int:
        return struct.unpack(">h", self.read(2))[0]
    def read_int(self) -> int:
        return struct.unpack(">i", self.read(4))[0]
    def read_long(self) -> int:
        return struct.unpack(">q", self.read(8))[0]
    def read_float(self):
        return struct.unpack(">f", self.read(4))[0]
    def read_double(self):
        return struct.unpack(">d", self.read(8))[0]
    def read_string(self) -> str:
        ln = self.read_short()
        if ln < 0:
            return ""
        raw = self.read(ln)
        try:
            return raw.decode("utf-8")
        except:
            return raw.decode("latin1", errors="replace")
    def parse_payload(self, tag_type:int):
        if tag_type == TAG_Byte: return self.read_byte()
        if tag_type == TAG_Short: return self.read_short()
        if tag_type == TAG_Int: return self.read_int()
        if tag_type == TAG_Long: return self.read_long()
        if tag_type == TAG_Float: return self.read_float()
        if tag_type == TAG_Double: return self.read_double()
        if tag_type == TAG_Byte_Array:
            length = self.read_int()
            return list(self.read(length))
        if tag_type == TAG_String:
            return self.read_string()
        if tag_type == TAG_List:
            inner = self.read_ubyte()
            length = self.read_int()
            items = []
            for _ in range(length):
                items.append(self.parse_payload(inner))
            return items
        if tag_type == TAG_Compound:
            d = {}
            while True:
                t = self.read_ubyte()
                if t == TAG_End:
                    break
                key = self.read_string()
                d[key] = self.parse_payload(t)
            return d
        if tag_type == TAG_Int_Array:
            length = self.read_int()
            return [self.read_int() for _ in range(length)]
        if tag_type == TAG_Long_Array:
            length = self.read_int()
            return [self.read_long() for _ in range(length)]
        raise ValueError(f"Unsupported NBT tag {tag_type}")
    def parse_root(self) -> Dict[str,Any]:
        t = self.read_ubyte()
        if t != TAG_Compound:
            raise ValueError("Root not a compound")
        name = self.read_string()  # often empty
        return self.parse_payload(TAG_Compound)

# --------------- Region parsing ----------------
def read_region_file(path: str) -> List[Tuple[int, Dict]]:
    """
    Returns list of (chunk_index, parsed_root_nbt) for chunks that exist in this region.
    """
    results = []
    with open(path, "rb") as f:
        header = f.read(8192)
        if len(header) < 8192:
            return results
        offsets = [struct.unpack(">I", header[i:i+4])[0] for i in range(0,4096,4)]
        offsets = [(val >> 8, val & 0xFF) for val in offsets]  # (sector_offset, sector_count)
        for i,(sector_off, sector_count) in enumerate(offsets):
            if sector_off == 0:
                continue
            f.seek(sector_off * 4096)
            length_bytes = f.read(4)
            if len(length_bytes) < 4: 
                continue
            length = struct.unpack(">I", length_bytes)[0]
            if length == 0:
                continue
            comp_type_b = f.read(1)
            if not comp_type_b:
                continue
            comp_type = comp_type_b[0]
            comp_data = f.read(length - 1)
            try:
                if comp_type == 1:
                    decompressed = gzip.decompress(comp_data)
                elif comp_type == 2:
                    decompressed = zlib.decompress(comp_data)
                else:
                    # unknown compression
                    continue
            except Exception as e:
                print(f"[WARN] failed decompress chunk {i} in {os.path.basename(path)}: {e}")
                continue
            try:
                reader = NBTReader(decompressed)
                nbt = reader.parse_root()
                results.append((i, nbt))
            except Exception as e:
                print(f"[WARN] failed parse NBT for chunk {i} in {os.path.basename(path)}: {e}")
                continue
    return results

# --------------- BlockEntity extraction ----------------
def get_block_entities_from_chunk_nbt(nbt: Dict) -> List[Dict]:
    # normalize level field names
    level = nbt.get("Level") or nbt.get("level") or nbt
    for key in ("BlockEntities","block_entities","TileEntities"):
        if key in level and isinstance(level[key], list):
            return level[key]
    return []

def is_storage_entity_id(beid: str) -> bool:
    if not isinstance(beid, str):
        return False
    beid_low = beid.lower()
    # try to canonicalize "minecraft:blue_shulker_box" variants
    if ":" in beid_low:
        # check prefix
        return any(beid_low.startswith(s) for s in STORAGE_IDS)
    else:
        return ("minecraft:" + beid_low) in STORAGE_IDS

def should_save_storage(be: Dict) -> bool:
    # Save if Items present (even empty) -> generated
    if "Items" in be or "items" in be:
        return True
    # If LootTable present but no Items -> ungenerated; skip
    if "LootTable" in be and "Items" not in be and "items" not in be:
        return False
    # otherwise keep (fallback)
    return True

def normalize_storage(be: dict, region_file: str, chunk_index: int) -> dict:
    be_id = be.get("id") or be.get("Id") or be.get("ID") or ""
    x = int(be.get("x") or be.get("X") or be.get("posX") or 0)
    y = int(be.get("y") or be.get("Y") or be.get("posY") or 0)
    z = int(be.get("z") or be.get("Z") or be.get("posZ") or 0)
    items_raw = be.get("Items") or be.get("items") or []
    items = []

    for it in items_raw:
        if not isinstance(it, dict):
            continue

        # --- Clean item_id ---
        raw_id = it.get("id") or it.get("Name") or ""
        if not raw_id:
            continue
        if raw_id.startswith("minecraft:"):
            item_id = raw_id.split("minecraft:")[1]
        else:
            item_id = raw_id

        # --- Parse count as int ---
        cnt = it.get("Count") or it.get("count") or 0
        try:
            count = int(cnt)
        except Exception:
            count = 0

        # --- Slot ---
        slot = it.get("Slot") if isinstance(it.get("Slot", None), int) else None

        # --- Display name ---
        tag = it.get("tag") or {}
        display_name = None
        if isinstance(tag, dict):
            display = tag.get("display") or {}
            display_name = display.get("Name")
        # fallback to plain item_id if no custom name
        if not display_name:
            display_name = item_id

        items.append({
            "slot": slot,
            "item_id": item_id,       # <--- no more minecraft: prefix
            "count": count,           # <--- proper int
            "display_name": display_name,
            "raw": it
        })

    return {
        "region_file": os.path.basename(region_file),
        "chunk_index": chunk_index,
        "entity_id": be_id,
        "x": x, "y": y, "z": z,
        "items": items,
        "raw_nbt": be
    }

# --------------- Postgres upsert ----------------
def upsert_storage_and_items(conn, normalized: dict):
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO storages (world_name, region_file, chunk_index, entity_id, x, y, z, raw_nbt)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
      ON CONFLICT (x,y,z) DO UPDATE SET
        world_name = EXCLUDED.world_name,
        region_file = EXCLUDED.region_file,
        chunk_index = EXCLUDED.chunk_index,
        entity_id = EXCLUDED.entity_id,
        updated_at = now(),
        raw_nbt = EXCLUDED.raw_nbt
      RETURNING storage_id
    """, (
        WORLD_NAME,
        normalized["region_file"],
        normalized["chunk_index"],
        normalized["entity_id"],
        normalized["x"], normalized["y"], normalized["z"],
        Json(normalized["raw_nbt"])
    ))
    storage_id = cur.fetchone()[0]

    # Delete old items and reinsert
    cur.execute("DELETE FROM storage_items WHERE storage_id = %s", (storage_id,))
    for it in normalized["items"]:
        cur.execute("""
          INSERT INTO storage_items (storage_id, slot, item_id, count, display_name, raw_item_nbt)
          VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            storage_id,
            it.get("slot"),
            it.get("item_id"),
            it.get("count"),
            it.get("display_name"),
            Json(it.get("raw"))
        ))
    return storage_id

# --------------- Runner ----------------
def process_region_file(conn, path: str) -> int:
    print(f"[INFO] Processing {os.path.basename(path)}")
    count_saved = 0
    chunks = read_region_file(path)
    for chunk_index, nbt in chunks:
        for be in get_block_entities_from_chunk_nbt(nbt):
            be_id = be.get("id") or be.get("Id") or be.get("ID") or ""
            # filter by id heuristics
            if not is_storage_entity_id(be_id):
                continue
            # filter ungenerated loot chests
            if not should_save_storage(be):
                continue
            normalized = normalize_storage(be, path, chunk_index)
            try:
                upsert_storage_and_items(conn, normalized)
                count_saved += 1
            except Exception as e:
                print(f"[ERROR] DB upsert error for storage at {normalized['x']},{normalized['y']},{normalized['z']}: {e}")
                conn.rollback()
    conn.commit()
    print(f"[INFO] Saved/Updated {count_saved} storages from {os.path.basename(path)}")
    return count_saved

def find_region_files(dirpath: str) -> List[str]:
    if not os.path.isdir(dirpath):
        return []
    files = [os.path.join(dirpath, f) for f in os.listdir(dirpath) if f.endswith(".mca")]
    files.sort()
    return files

def main():
    region_files = find_region_files(REGION_DIR)
    if not region_files:
        print("[ERROR] No region files found in", REGION_DIR)
        return
    conn = psycopg2.connect(**DB_CONNECT_KW)
    total = 0
    try:
        for rf in region_files:
            total += process_region_file(conn, rf)
    finally:
        conn.close()
    print(f"[DONE] Total storages processed: {total}")

if __name__ == "__main__":
    main()
