#!/usr/bin/env python3
import psycopg2
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
import matplotlib.colors as mcolors
import math

DB_CONNECT_KW = {
    "dbname": "minecraft_world",
    "user": "un_project_user",
    "password": "passtheword",
    "host": "localhost",
    "port": 5432
}

# Connect and fetch data
conn = psycopg2.connect(**DB_CONNECT_KW)
cur = conn.cursor()
cur.execute("SELECT x, y, z, entity_id FROM storages;")
rows = cur.fetchall()
cur.close()
conn.close()

if not rows:
    print("No storages found.")
    exit()

# Extract columns
xs = [r[0] for r in rows]
ys = [r[1] for r in rows]  # height (used for color)
zs = [r[2] for r in rows]
types = [r[3].lower() for r in rows]

unique_types = sorted(set(types))

# Center the scale around Y=63
norm = mcolors.TwoSlopeNorm(vmin=-50, vcenter=63, vmax=150)
cmap = plt.cm.viridis

# Plot setup
fig, ax = plt.subplots(figsize=(8, 8))
plt.subplots_adjust(bottom=0.25 + (0.05 * math.ceil(len(unique_types) / 3)))

sc = ax.scatter(xs, zs, c=ys, cmap=cmap, norm=norm, s=8, alpha=0.8)
ax.set_title("All Storages (colored by height, centered at Y=63)")
ax.set_xlabel("X coordinate")
ax.set_ylabel("Z coordinate")
ax.invert_yaxis()
plt.grid(True)

# Colorbar
cbar = plt.colorbar(sc, ax=ax)
cbar.set_label("Y (height, centered at 63)")

# --- Update function for filtering ---
def update_display(filter_type=None):
    if not filter_type:
        filtered = list(zip(xs, zs, ys))
        title = "All Storages (colored by height, centered at Y=63)"
    else:
        filtered = [(x, z, y) for x, z, y, t in zip(xs, zs, ys, types) if t == filter_type]
        title = f"{filter_type} (colored by height, centered at Y=63)"

    if not filtered:
        sc.set_offsets([])
        sc.set_array([])
    else:
        fx, fz, fy = zip(*filtered)
        sc.set_offsets(list(zip(fx, fz)))
        sc.set_array(fy)

    ax.set_title(title)
    fig.canvas.draw_idle()

# --- Button layout ---
buttons = []
cols = 3

# "Show All" button
ax_all = plt.axes([0.05, 0.05, 0.2, 0.05])
btn_all = Button(ax_all, 'Show All')
btn_all.on_clicked(lambda event: update_display(None))
buttons.append(btn_all)

# Buttons for each storage type
for i, t in enumerate(unique_types):
    col = i % cols
    row = i // cols
    left = 0.05 + col * 0.3
    bottom = 0.12 + row * 0.06
    ax_btn = plt.axes([left, bottom, 0.25, 0.05])
    display_label = t.replace("minecraft:", "")
    btn = Button(ax_btn, display_label.capitalize())
    btn.on_clicked(lambda event, ft=t: update_display(ft))
    buttons.append(btn)

plt.show()
