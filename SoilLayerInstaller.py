#!/usr/bin/env python3
"""
SoilLayerInstaller.py
Injects custom soil density map layers into any FS25 map mod so that
FS25_SoilFertilizer can use per-pixel N/P/K/pH/OM tracking.

HOW IT WORKS
  1. Finds the active savegame and identifies the current map mod zip.
  2. Backs up the original zip.
  3. Patches maps/mapEU.i3d inside the zip:
       - Adds 5 File entries for the new GRLE data files.
       - Adds 8 InfoLayer entries (soilN / soilP / soilK / soilPH / soilOM / soilPest / soilDisease / soilCompaction).
  4. Copies an existing blank GRLE from the zip as the initial data for
     each new layer (all zeros = safe starting state).
  5. On the next game load the engine auto-creates/registers the layers.
     FS25_SoilFertilizer detects them via getInfoLayerFromTerrain() and
     uses per-pixel reads/writes instead of the field-average fallback.

USAGE
  Run once, then reload FS25.  Safe to re-run (detects existing patches).
"""

import os, sys, re, shutil, struct, zipfile, zlib

# ─── Configuration ────────────────────────────────────────────────────────────

def _get_documents_dir():
    # Query the Windows Shell for the real Documents path.
    # This correctly handles OneDrive redirection, custom folder locations,
    # and any other non-standard Documents placements.
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
        path, _ = winreg.QueryValueEx(key, "Personal")
        winreg.CloseKey(key)
        if path and os.path.isdir(path):
            return path
    except Exception:
        pass
    return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Documents")

_DOCS    = _get_documents_dir()
MODS_DIR  = os.path.join(_DOCS, "My Games", "FarmingSimulator2025", "mods")
SAVES_DIR = os.path.join(_DOCS, "My Games", "FarmingSimulator2025")

# The 5 soil layers we inject.  Name = i3d short name (engine prefixes infoLayer_).
SOIL_LAYERS = [
    # Nutrients
    {"name": "soilN",          "field": "nitrogen",        "numChannels": 8},
    {"name": "soilP",          "field": "phosphorus",      "numChannels": 8},
    {"name": "soilK",          "field": "potassium",       "numChannels": 8},
    {"name": "soilPH",         "field": "pH",              "numChannels": 8},
    {"name": "soilOM",         "field": "organicMatter",   "numChannels": 8},
    # Biotic / physical pressure
    {"name": "soilPest",       "field": "pestPressure",    "numChannels": 8},
    {"name": "soilDisease",    "field": "diseasePressure", "numChannels": 8},
    {"name": "soilCompaction", "field": "compaction",      "numChannels": 8},
    # weed: read-only from game's native weed density map — not installed here
]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def find_savegame():
    """Return the path of the first savegame directory that has a careerSavegame.xml."""
    for i in range(1, 21):
        path = os.path.join(SAVES_DIR, f"savegame{i}", "careerSavegame.xml")
        if os.path.exists(path):
            return os.path.dirname(path)
    return None

def find_map_id(savegame_dir):
    """Parse careerSavegame.xml and return the mapId string."""
    career = os.path.join(savegame_dir, "careerSavegame.xml")
    with open(career, encoding="utf-8-sig", errors="ignore") as f:
        content = f.read()
    m = re.search(r"<mapId>([^<]+)</mapId>", content)
    return m.group(1) if m else None

def find_map_zip(map_id):
    """
    map_id is like 'FS25_The_Pichonniere_Valley.SampleModMap'.
    The mod zip name is the part before the first dot: FS25_The_Pichonniere_Valley.zip
    """
    mod_name = map_id.split(".")[0]
    zip_path = os.path.join(MODS_DIR, mod_name + ".zip")
    if os.path.exists(zip_path):
        return zip_path
    # Fallback: case-insensitive search
    for f in os.listdir(MODS_DIR):
        if f.lower() == (mod_name + ".zip").lower():
            return os.path.join(MODS_DIR, f)
    return None

def find_i3d_path(z):
    """Find the main map i3d file inside the zip.

    Handles all common FS25 map structures:
      maps/mapXX.i3d   (standard Giants layout)
      map/mapXX.i3d    (alternate single-folder layout)
      mapXX.i3d        (root-level layout)
      SomeFolder/data/mapXX.i3d  (deep custom layout)
    """
    names = z.namelist()

    # 1. Prefer shallow entries (depth 0 or 1) that contain "map" in the filename.
    def filename_part(p):
        return p.rsplit("/", 1)[-1].lower()

    shallow = sorted(
        [f for f in names if f.endswith(".i3d") and f.count("/") <= 1],
        key=lambda f: f.count("/")   # root-level before single-folder
    )
    # Among shallow candidates, prefer ones with "map" in the filename.
    preferred = [f for f in shallow if "map" in filename_part(f)]
    if preferred:
        return preferred[0]
    if shallow:
        return shallow[0]

    # 2. Any depth — prefer shallower, prefer "map" in filename.
    all_i3d = sorted(
        [f for f in names if f.endswith(".i3d")],
        key=lambda f: (f.count("/"), "map" not in filename_part(f))
    )
    return all_i3d[0] if all_i3d else None


def get_data_dir(i3d_path):
    """Return the zip-absolute data directory for GRLE files, derived from the i3d location.

    Examples:
      maps/mapEU.i3d  → maps/data/
      map/mapEU.i3d   → map/data/
      mapEU.i3d       → data/
    """
    if "/" in i3d_path:
        i3d_folder = i3d_path.rsplit("/", 1)[0] + "/"
    else:
        i3d_folder = ""
    return i3d_folder + "data/"

def make_blank_png_1024():
    """Generate a blank 1024×1024 8-bit grayscale PNG (all zeros).

    Uses only Python stdlib (zlib + struct). FS25 reads this as 8 bits per
    pixel, which matches numChannels=8 declared in the i3d InfoLayer entry.
    """
    W = H = 1024

    def _chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)

    sig  = b'\x89PNG\r\n\x1a\n'
    ihdr = _chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 0, 0, 0, 0))
    raw  = (b'\x00' + b'\x00' * W) * H   # filter byte + row pixels, repeated
    idat = _chunk(b'IDAT', zlib.compress(raw, 9))
    iend = _chunk(b'IEND', b'')
    return sig + ihdr + idat + iend

def get_missing_layers(i3d_content):
    """Return the SOIL_LAYERS entries whose InfoLayer is NOT yet in the i3d."""
    return [
        layer for layer in SOIL_LAYERS
        if f'name="{layer["name"]}"' not in i3d_content
        and f'infoLayer_{layer["name"]}.grle' not in i3d_content
        and f'infoLayer_{layer["name"]}.png' not in i3d_content
    ]

def already_patched(i3d_content):
    """Return True only if ALL 8 soil layers are present in the i3d."""
    return len(get_missing_layers(i3d_content)) == 0

def get_max_file_id(i3d_content):
    """Return the highest fileId integer found in the i3d."""
    ids = [int(m) for m in re.findall(r'fileId="(\d+)"', i3d_content)]
    return max(ids) if ids else 1000

def patch_files_section(i3d_content, new_files):
    """
    Insert <File .../> entries before the closing </Files> tag.
    new_files: list of (fileId, filename) tuples
    """
    insert = "\n" + "\n".join(
        f'        <File fileId="{fid}" filename="{fn}"/>'
        for fid, fn in new_files
    ) + "\n"
    return re.sub(r"(\s*</Files>)", insert + r"\1", i3d_content, count=1)

def find_last_infolayer_end(i3d_content):
    """
    Return the index just AFTER the last </InfoLayer> or self-closing InfoLayer.
    We insert our new InfoLayer blocks there.
    """
    # Match both <InfoLayer .../> and <InfoLayer ...>...</InfoLayer>
    pattern = re.compile(r'<InfoLayer\b[^>]*(?:/>|>.*?</InfoLayer>)', re.DOTALL)
    last_match = None
    for m in pattern.finditer(i3d_content):
        last_match = m
    if last_match:
        return last_match.end()
    return None

def patch_infolayer_section(i3d_content, new_layers):
    """
    Insert InfoLayer entries after the last existing InfoLayer block.
    new_layers: list of (name, fileId, numChannels)
    """
    insert_pos = find_last_infolayer_end(i3d_content)
    if insert_pos is None:
        print("  WARNING: Could not find InfoLayer section — patch skipped")
        return i3d_content

    insert = "\n" + "\n".join(
        f'        <InfoLayer name="{name}" fileId="{fid}" numChannels="{nc}" runtime="true"/>'
        for name, fid, nc in new_layers
    )
    return i3d_content[:insert_pos] + insert + i3d_content[insert_pos:]

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  FS25 SoilFertilizer — Density Layer Installer")
    print("=" * 60)

    # 1. Find active savegame
    savegame_dir = find_savegame()
    if not savegame_dir:
        print("ERROR: No savegame found.")
        sys.exit(1)
    print(f"\nSavegame : {savegame_dir}")

    # 2. Find current map
    map_id = find_map_id(savegame_dir)
    if not map_id:
        print("ERROR: Could not read mapId from careerSavegame.xml")
        sys.exit(1)
    print(f"Map ID   : {map_id}")

    # 3. Find map zip
    zip_path = find_map_zip(map_id)
    if not zip_path:
        print(f"ERROR: Could not find map zip for '{map_id}' in {MODS_DIR}")
        sys.exit(1)
    print(f"Map zip  : {zip_path}")

    # 4. Open zip, find i3d
    with zipfile.ZipFile(zip_path, "r") as z:
        i3d_path = find_i3d_path(z)
        if not i3d_path:
            print("ERROR: Could not find main .i3d file inside the zip.")
            sys.exit(1)
        print(f"i3d file : {i3d_path}")

        i3d_content = z.read(i3d_path).decode("utf-8-sig", errors="ignore")

        # 5. Check which layers are missing
        missing_layers = get_missing_layers(i3d_content)
        if not missing_layers:
            print("\nMap is already fully patched (all 8 layers present). Nothing to do.")
            print("If you need to re-patch, restore the backup zip and re-run.")
            sys.exit(0)

        if len(missing_layers) < len(SOIL_LAYERS):
            present = len(SOIL_LAYERS) - len(missing_layers)
            print(f"\nPartial patch detected: {present}/8 layers present.")
            print(f"Adding {len(missing_layers)} missing layer(s): "
                  + ", ".join(l["name"] for l in missing_layers))
        else:
            print(f"\nFresh install: adding all {len(SOIL_LAYERS)} layers.")

        # Derive the data directory from the actual i3d location so we work
        # regardless of whether the map uses maps/, map/, or a custom folder.
        data_dir = get_data_dir(i3d_path)
        print(f"Data dir : {data_dir}")

        # 6. Generate a blank 1024×1024 8-bit grayscale PNG for each new layer.
        #    PNG is unambiguous: 8 bits per pixel matches numChannels=8 in the i3d.
        blank_data = make_blank_png_1024()
        print(f"\nBlank PNG: <generated 1024×1024 grayscale> ({len(blank_data):,} bytes)")

        # Snapshot all existing files so we can repack
        existing_files = {}
        for item in z.namelist():
            existing_files[item] = z.read(item)

    # 7. Backup original zip
    backup_path = zip_path + ".backup_soilinstaller"
    if not os.path.exists(backup_path):
        shutil.copy2(zip_path, backup_path)
        print(f"Backup   : {backup_path}")
    else:
        print(f"Backup   : already exists — skipping copy")

    # 8. Compute new fileIds (only for missing layers)
    max_fid = get_max_file_id(i3d_content)
    new_file_entries = []
    new_layer_entries = []
    new_grle_files = {}

    for i, layer in enumerate(missing_layers):
        fid  = max_fid + 1 + i
        name = layer["name"]
        nc   = layer["numChannels"]
        png_zip_path = f"{data_dir}infoLayer_{name}.png"
        i3d_rel_path = f"data/infoLayer_{name}.png"

        new_file_entries.append((fid, i3d_rel_path))
        new_layer_entries.append((name, fid, nc))
        new_grle_files[png_zip_path] = blank_data

    print(f"\nAssigning fileIds {max_fid+1} – {max_fid+len(missing_layers)} for new layers")
    for (name, fid, nc), (_, i3d_fn) in zip(new_layer_entries, new_file_entries):
        print(f"  fileId={fid}  name={name!r}  -> {i3d_fn}")

    # 9. Patch i3d
    patched_i3d = patch_files_section(i3d_content, new_file_entries)
    patched_i3d = patch_infolayer_section(patched_i3d, new_layer_entries)

    # Quick sanity check
    for name, _, _ in new_layer_entries:
        if f'name="{name}"' not in patched_i3d:
            print(f"  WARNING: InfoLayer for '{name}' may not have been inserted correctly!")

    # 10. Repack zip
    print(f"\nRepacking zip...")
    tmp_path = zip_path + ".tmp"
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zout:
        for item_path, data in existing_files.items():
            if item_path == i3d_path:
                zout.writestr(item_path, patched_i3d.encode("utf-8"))
            else:
                zout.writestr(item_path, data)
        # Add new GRLE files
        for grle_path, data in new_grle_files.items():
            zout.writestr(grle_path, data)
            print(f"  + {grle_path} ({len(data):,} bytes)")

    # Replace original
    os.replace(tmp_path, zip_path)
    print(f"\nZip updated: {zip_path}")

    # 11. Verify
    print("\nVerifying patch...")
    with zipfile.ZipFile(zip_path, "r") as z:
        i3d_check = z.read(i3d_path).decode("utf-8-sig", errors="ignore")
        ok = True
        for layer in SOIL_LAYERS:
            name = layer["name"]
            png  = f"{data_dir}infoLayer_{name}.png"
            if f'name="{name}"' in i3d_check:
                print(f"  [OK] InfoLayer name={name!r} in i3d")
            else:
                print(f"  [!!] MISSING: InfoLayer name={name!r}")
                ok = False
            if png in z.namelist():
                print(f"  [OK] {png} present in zip")
            else:
                print(f"  [!!] MISSING: {png}")
                ok = False

    print()
    if ok:
        print("SUCCESS — all 8 soil layers injected.")
        print()
        print("NEXT STEPS:")
        print("  1. Reload FS25 (or load your savegame).")
        print("  2. The engine registers the layers on terrain load.")
        print("  3. Check log.txt for '[SoilFertilizer] Soil layer registered: soilN'")
        print("     (and soilP, soilK, soilPH, soilOM, soilPest, soilDisease, soilCompaction).")
        print("  4. If you see those messages, per-pixel soil tracking is active!")
        print()
        print("NOTE: FS25_SoilFertilizer must be built with short layer names")
        print("  (soilN / soilP / soilK / soilPH / soilOM / soilPest / soilDisease / soilCompaction) for detection to work.")
    else:
        print("PARTIAL SUCCESS — some layers may be missing. Check warnings above.")

if __name__ == "__main__":
    main()
