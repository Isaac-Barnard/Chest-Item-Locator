import os
import re
import json
import psycopg2
from anvil import Region
from psycopg2.extras import execute_values


OVERRIDE_PARSE = False


STORAGE_BASE_TYPES = {"minecraft:chest", "minecraft:trapped_chest", "minecraft:barrel",
                      "minecraft:shulker_box", "minecraft:dispenser", "minecraft:dropper",
                      "minecraft:hopper", "minecraft:furnace", "minecraft:blast_furnace", "minecraft:smoker",
                      "minecraft:chiseled_bookshelf", "minecraft:decorated_pot", "minecraft:brewing_stand",
                      "minecraft:lectern", "minecraft:crafter", "minecraft:shelf"}

STORAGE_PATTERNS = [
    re.compile(r"minecraft:.+_shulker_box$")
]

REGION_DIR = os.path.join(os.path.dirname(__file__), "region")

DB_CONNECT_KW = {
    "dbname": "minecraft_world",
    "user": "website",           # or your DB user
    "password": "Bl0ckG@me",   # set this to your Postgres password
    "host": "localhost",
    "port": 5432
}


def is_storage_block(block_id: str) -> bool:
    if block_id in STORAGE_BASE_TYPES:
        return True
    return any(p.match(block_id) for p in STORAGE_PATTERNS)

def is_valid_storage(keys: list) -> bool:
    if "Items" in keys or "items" in keys:
        return True
    
    if "LootTable" in keys and "Items" not in keys and "items" not in keys:
        return False
    
    return True

def trim_id(item_id: str) -> str:
    return item_id.split('minecraft:')[-1]

def get_sub_storage_contents(container, slot_prepend, item_json):
    container_items = []
    
    for item in container:
        sub_count = 0

        slot = item.get('slot') or item.get('Slot')
        if slot:
            slot = slot_prepend + slot.value * -1
        else:
            slot = -1
        inner = item.get('item')
        if inner:
            count = inner.get('Count') or inner.get('count')
            item_id = inner.get('id') or inner.get('Id') or inner.get('ID')
        else:
            count = item.get('Count') or item.get('count')
            item_id = item.get('id') or item.get('Id') or item.get('ID')

        item_json.append({
            "id": trim_id(item_id.value),
            "count": count.value,
            "slot": slot,
            "display_name": item_id.value
        })

        components = item.get('components') or item.get('Components')
        if components:
            container = (
                        components.get('minecraft:container')
                        or components.get('container')
                        or components.get('minecraft:bundle_contents')
                        or components.get('bundle_contents')
                        )
            if container:
                sub_count += 1
                item_json.append(get_sub_storage_contents(container, slot_prepend + sub_count * -1000, item_json))

def get_all_storages(region_path):
    print (f"Beginning to parse region files from {region_path}")
    directory = os.listdir(region_path)
    directory.sort()

    storage_data = []
    for file in directory:
        region = Region.from_file(os.path.join(region_path, file))
        region_data = []

        for x in range(32):
            for z in range(32):
                chunk_data = region.chunk_data(x, z)
                if not chunk_data:
                    continue

                block_entities = chunk_data['block_entities']
                if len(block_entities) == 0:
                    continue

                for entity in block_entities:
                    sub_count = 0
                    entity_id = entity.get('id').value
                    
                    if not is_storage_block(entity_id):
                        continue
                    
                    if not is_valid_storage(entity.keys()):
                        continue
                    
                    items_tag = entity.get("Items") or entity.get("items") or []
                    items = []

                    for item in items_tag:
                        count = item.get("Count") or item.get("count")
                        slot = item.get("Slot") or item.get("slot")
                        item_id = item.get("id") or item.get("Id") or item.get("ID")

                        items.append({
                                "id": trim_id(item_id.value),
                                "count": count.value,
                                "slot": slot.value,
                                "display_name": item_id.value
                        })

                        components = item.get('components') or item.get('Components')
                        if components:
                            container = (
                                        components.get('minecraft:container')
                                        or components.get('container')
                                        or components.get('minecraft:bundle_contents')
                                        or components.get('bundle_contents')
                                        )
                            if container:
                                sub_count += 1
                                get_sub_storage_contents(container, sub_count * -10000, items)

                    
                    region_data.append({
                        "entity_id": trim_id(entity_id),
                        "x": entity.get('x').value,
                        "y": entity.get('y').value,
                        "z": entity.get('z').value,
                        "items": items,
                        "region_file": file.split("/")[-1],
                        "chunk_relative_pos": f"{x},{z}",
                        "chunk_index": x * 32 + z
                    })
        storage_data.extend(region_data)
        print(f"Parsed {file}: {len(region_data)} storages found")
    
    print(f"Parsed {region_path}: {len(storage_data)} storages found")
    return storage_data

def write_to_json(jsondata):
    with open(os.path.join(os.path.dirname(__file__), 'output.json'), 'w', encoding='utf-8') as f:
        json.dump(jsondata, f, ensure_ascii=False, indent=2)

    print(f"Wrote storage json to {os.path.join(os.path.dirname(__file__), 'output.json')}")

def clear_tables(conn):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE storage_items CASCADE;")
        cur.execute("TRUNCATE TABLE storages RESTART IDENTITY CASCADE;")
        conn.commit()
        print("Cleared storage tables.")

def bulk_insert_storage(conn, all_storage_data):
    """Insert all storages and items efficiently."""
    with conn.cursor() as cur:
        # --- Insert storages in bulk ---
        storage_values = [
            (
                s["region_file"],
                s["chunk_index"],
                s["chunk_relative_pos"],
                s["entity_id"],
                s["x"],
                s["y"],
                s["z"],
            )
            for s in all_storage_data
        ]

        storage_insert_query = """
            INSERT INTO storages (
                region_file, chunk_index, chunk_relative_pos, entity_id, x, y, z
            )
            VALUES %s
            ON CONFLICT (x, y, z) DO NOTHING;
        """
        execute_values(cur, storage_insert_query, storage_values)
        conn.commit()

        
        cur.execute("SELECT storage_id, x, y, z FROM storages;")
        coord_rows = cur.fetchall()
        # Map coordinates to storage_id for item insertion
        coord_to_id = {(x, y, z): storage_id for storage_id, x, y, z in coord_rows}

        # --- Insert items in bulk ---
        item_values = []
        for s in all_storage_data:
            storage_id = coord_to_id[(s["x"], s["y"], s["z"])]
            for item in s["items"]:
                if not item:
                    continue
                item_values.append(
                    (
                        storage_id,
                        item.get("slot"),
                        item.get("id"),
                        item.get("count"),
                        None,  # display_name placeholder
                    )
                )

        if item_values:
            item_insert_query = """
                INSERT INTO storage_items (storage_id, slot, item_id, count, display_name)
                VALUES %s
            """
            execute_values(cur, item_insert_query, item_values)

        conn.commit()
        print(f"Inserted {len(all_storage_data)} storages with {len(item_values)} items.")



def main():
    if not OVERRIDE_PARSE:
        all_storage_data = get_all_storages(REGION_DIR)
        print("Parsed all region files")
        write_to_json(all_storage_data)
    else:
        with open(os.path.join(os.path.dirname(__file__), 'output.json'), "r", encoding="utf-8") as f:
            all_storage_data = json.load(f)

    conn = psycopg2.connect(**DB_CONNECT_KW)
    clear_tables(conn)
    bulk_insert_storage(conn, all_storage_data)
    conn.close()

if __name__ == "__main__":
    main()