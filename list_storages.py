#!/usr/bin/env python3
import psycopg2
import matplotlib.pyplot as plt

DB_CONNECT_KW = {
    "dbname": "minecraft_world",
    "user": "un_project_user",
    "password": "passtheword",
    "host": "localhost",
    "port": 5432
}

conn = psycopg2.connect(**DB_CONNECT_KW)
cur = conn.cursor()
cur.execute("SELECT x, y, z, entity_id FROM storages;")

rows = cur.fetchall()

# Print a simple list
for x, y, z, entity_id in rows:
    print(f"{entity_id:<25} ({x}, {y}, {z})")

# Separate coordinates
xs = [r[0] for r in rows]
ys = [r[1] for r in rows]  # Y = height
zs = [r[2] for r in rows]

# Create scatter plot with color mapped to Y (height)
plt.figure(figsize=(8,8))
scatter = plt.scatter(xs, zs, c=ys, cmap='viridis', s=8, alpha=0.8)

plt.title("Storage Block Locations (XZ plane, colored by height)")
plt.xlabel("X coordinate")
plt.ylabel("Z coordinate")

# Invert Z axis for Minecraft-style map
plt.gca().invert_yaxis()

# Add colorbar to show Y values
cbar = plt.colorbar(scatter)
cbar.set_label("Y (height)")

plt.grid(True)
plt.show()

cur.close()
conn.close()
