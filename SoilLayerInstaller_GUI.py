#!/usr/bin/env python3
"""
FS25 SoilFertilizer — Soil Layer Installer  (GUI v2)
Tabbed UI: Installer | Settings | Log
"""

import os, re, shutil, zipfile, threading, datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_VERSION = "1.2.0"

# ── Palette (Catppuccin Mocha) ─────────────────────────────────────────────────
BG      = "#1e1e2e"
SURFACE = "#181825"
PANEL   = "#2a2a3e"
OVERLAY = "#313244"
BORDER  = "#45475a"
GREEN   = "#a6e3a1"
BLUE    = "#89b4fa"
YELLOW  = "#f9e2af"
RED     = "#f38ba8"
ORANGE  = "#fab387"
TEXT    = "#cdd6f4"
SUBTEXT = "#a6adc8"
DIM     = "#6c7086"

H1 = ("Segoe UI", 14, "bold")
H2 = ("Segoe UI", 11, "bold")
H3 = ("Segoe UI", 10, "bold")
BD = ("Segoe UI", 10)
SM = ("Segoe UI", 9)
MN = ("Consolas", 9)
BT = ("Segoe UI", 12, "bold")

# ── Documents path (OneDrive-aware) ───────────────────────────────────────────
def _get_documents():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
        p, _ = winreg.QueryValueEx(k, "Personal")
        winreg.CloseKey(k)
        if p and os.path.isdir(p):
            return p
    except Exception:
        pass
    return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Documents")

DOCS      = _get_documents()
DEF_SAVES = os.path.join(DOCS, "My Games", "FarmingSimulator2025")
DEF_MODS  = os.path.join(DOCS, "My Games", "FarmingSimulator2025", "mods")

# ── FS25 game installation detection ──────────────────────────────────────────

def find_game_dir():
    """Find FS25 installation directory via registry, Steam libraries, and common paths."""
    try:
        import winreg
        for reg_path in [
            r"SOFTWARE\GIANTS Software GmbH\FarmingSimulator2025",
            r"SOFTWARE\WOW6432Node\GIANTS Software GmbH\FarmingSimulator2025",
        ]:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
                val, _ = winreg.QueryValueEx(key, "InstallPath")
                winreg.CloseKey(key)
                if val and os.path.isdir(val):
                    return val
            except Exception:
                pass
    except Exception:
        pass

    # Steam — find all library paths via libraryfolders.vdf
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")
        steam_path, _ = winreg.QueryValueEx(key, "InstallPath")
        winreg.CloseKey(key)
        lib_paths = [steam_path]
        vdf = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
        if os.path.exists(vdf):
            with open(vdf, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    m = re.search(r'"path"\s+"([^"]+)"', line)
                    if m:
                        lib_paths.append(m.group(1).replace("\\\\", "\\"))
        for lib in lib_paths:
            p = os.path.join(lib, "steamapps", "common", "Farming Simulator 25")
            if os.path.isdir(p):
                return p
    except Exception:
        pass

    for p in [
        r"C:\Program Files (x86)\Farming Simulator 2025",
        r"C:\Program Files\Farming Simulator 2025",
        r"C:\Games\Farming Simulator 2025",
    ]:
        if os.path.isdir(p):
            return p
    return None

DEF_GAME_DIR = find_game_dir()

# Known base-game mapId prefixes → folder name inside {game_dir}/data/maps/
KNOWN_BASE_MAPS = {
    "MapUS":     "mapUS",
    "MapEU":     "mapEU",
    "MapAlpine": "mapAlpine",
    "MapCA":     "mapCA",
    "MapFR":     "mapFR",
}

def find_base_game_map(map_id, game_dir):
    """
    For non-mod (base game) maps, locate the i3d file in the FS25 install dir.
    Returns {"i3d_path": str, "data_dir": str} or None.
    """
    if not game_dir or not os.path.isdir(game_dir):
        return None
    map_short = map_id.split(".")[0]
    maps_root = os.path.join(game_dir, "data", "maps")

    # Candidate folder names in priority order
    candidates = []
    if map_short in KNOWN_BASE_MAPS:
        candidates.append(KNOWN_BASE_MAPS[map_short])
    candidates += [
        map_short[0].lower() + map_short[1:],  # MapUS → mapUS
        map_short.lower(),                       # MapUS → mapus
        map_short,                               # as-is
    ]
    # Deduplicate while preserving order
    seen = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    for folder in candidates:
        # Structure 1: {maps_root}/{folder}/{folder}.i3d
        i3d = os.path.join(maps_root, folder, folder + ".i3d")
        if os.path.exists(i3d):
            return {"i3d_path": i3d,
                    "data_dir": os.path.join(maps_root, folder, "data")}
        # Structure 2: flat — {maps_root}/{folder}.i3d
        i3d = os.path.join(maps_root, folder + ".i3d")
        if os.path.exists(i3d):
            return {"i3d_path": i3d,
                    "data_dir": os.path.join(maps_root, "data")}
    return None

# ── Soil layer definitions ─────────────────────────────────────────────────────
SOIL_LAYERS = [
    {"name": "soilN",  "numChannels": 8},
    {"name": "soilP",  "numChannels": 8},
    {"name": "soilK",  "numChannels": 8},
    {"name": "soilPH", "numChannels": 8},
    {"name": "soilOM", "numChannels": 8},
]
BLANK_GRLE_SOURCE = "maps/data/infoLayer_fieldType.grle"

# ── Core patching helpers (UNCHANGED) ─────────────────────────────────────────

def find_map_id(savegame_dir):
    career = os.path.join(savegame_dir, "careerSavegame.xml")
    with open(career, encoding="utf-8-sig", errors="ignore") as f:
        content = f.read()
    m = re.search(r"<mapId>([^<]+)</mapId>", content)
    return m.group(1) if m else None

def find_map_zip(map_id, mods_dir):
    mod_name = map_id.split(".")[0]
    zip_path = os.path.join(mods_dir, mod_name + ".zip")
    if os.path.exists(zip_path):
        return zip_path
    try:
        for f in os.listdir(mods_dir):
            if f.lower() == (mod_name + ".zip").lower():
                return os.path.join(mods_dir, f)
    except Exception:
        pass
    return None

def find_i3d_path(z):
    candidates = [f for f in z.namelist() if f.endswith(".i3d") and f.count("/") == 1]
    if candidates:
        return candidates[0]
    for f in z.namelist():
        if f.endswith(".i3d") and "map" in f.lower():
            return f
    return None

def already_patched(i3d_content):
    return 'name="soilN"' in i3d_content

def get_max_file_id(i3d_content):
    ids = [int(m) for m in re.findall(r'fileId="(\d+)"', i3d_content)]
    return max(ids) if ids else 1000

def patch_files_section(i3d_content, new_files):
    insert = "\n" + "\n".join(
        f'        <File fileId="{fid}" filename="{fn}"/>'
        for fid, fn in new_files
    ) + "\n"
    return re.sub(r"(\s*</Files>)", insert + r"\1", i3d_content, count=1)

def find_last_infolayer_end(i3d_content):
    pattern = re.compile(r'<InfoLayer\b[^>]*(?:/>|>.*?</InfoLayer>)', re.DOTALL)
    last_match = None
    for m in pattern.finditer(i3d_content):
        last_match = m
    return last_match.end() if last_match else None

def patch_infolayer_section(i3d_content, new_layers):
    insert_pos = find_last_infolayer_end(i3d_content)
    if insert_pos is None:
        return i3d_content
    insert = "\n" + "\n".join(
        f'        <InfoLayer name="{name}" fileId="{fid}" numChannels="{nc}" runtime="true"/>'
        for name, fid, nc in new_layers
    )
    return i3d_content[:insert_pos] + insert + i3d_content[insert_pos:]

# ── Scanner ────────────────────────────────────────────────────────────────────

def scan_savegames(saves_dir, mods_dir, game_dir, log):
    """Return a list of dicts — one per found savegame slot."""
    results = []
    for i in range(1, 21):
        sg_path = os.path.join(saves_dir, f"savegame{i}")
        career  = os.path.join(sg_path, "careerSavegame.xml")
        if not os.path.exists(career):
            continue

        log("DEBUG", f"Slot savegame{i} — found careerSavegame.xml")

        try:
            map_id = find_map_id(sg_path)
        except Exception as e:
            log("WARNING", f"  Could not read map ID: {e}")
            map_id = None

        map_name    = map_id.split(".")[0] if map_id else "Unknown"
        zip_path    = None
        is_base     = False
        game_i3d    = None
        game_data   = None
        patched     = None
        has_backup  = False
        backup_path = None

        if map_id:
            # 1. Try mod ZIP first
            try:
                zip_path = find_map_zip(map_id, mods_dir)
                log("DEBUG", f"  map={map_name}  zip={'found' if zip_path else 'NOT FOUND'}")
            except Exception as e:
                log("WARNING", f"  ZIP lookup error: {e}")

            if zip_path:
                bp = zip_path + ".backup_soilinstaller"
                has_backup  = os.path.exists(bp)
                backup_path = bp
                try:
                    with zipfile.ZipFile(zip_path, "r") as z:
                        i3d = find_i3d_path(z)
                        if i3d:
                            raw     = z.read(i3d).decode("utf-8-sig", errors="ignore")
                            patched = already_patched(raw)
                            log("DEBUG", f"  i3d={i3d}  patched={patched}  backup={has_backup}")
                except Exception as e:
                    log("WARNING", f"  Could not inspect ZIP: {e}")
            else:
                # 2. Fall back to base game map detection
                info = find_base_game_map(map_id, game_dir)
                if info:
                    is_base    = True
                    game_i3d   = info["i3d_path"]
                    game_data  = info["data_dir"]
                    bp         = game_i3d + ".backup_soilinstaller"
                    has_backup  = os.path.exists(bp)
                    backup_path = bp
                    try:
                        with open(game_i3d, encoding="utf-8-sig", errors="ignore") as f:
                            raw     = f.read()
                        patched = already_patched(raw)
                        log("DEBUG", f"  base game i3d found  patched={patched}")
                    except Exception as e:
                        log("WARNING", f"  Could not read base game i3d: {e}")
                else:
                    log("DEBUG", f"  No ZIP and no base game map found for {map_name}")

        results.append({
            "slot":         i,
            "slot_name":    f"savegame{i}",
            "sg_path":      sg_path,
            "map_id":       map_id,
            "map_name":     map_name,
            "zip_path":     zip_path,
            "zip_name":     os.path.basename(zip_path) if zip_path else None,
            "is_base_game": is_base,
            "game_i3d":     game_i3d,
            "game_data_dir": game_data,
            "patched":      patched,
            "has_backup":   has_backup,
            "backup_path":  backup_path,
        })
    return results

# ── Base-game installer (patches loose files directly) ────────────────────────

def run_installer_base_game(sg, log, force=False):
    i3d_path = sg["game_i3d"]
    data_dir = sg["game_data_dir"]

    log("INFO", f"Savegame : {sg['slot_name']}")
    log("INFO", f"Map      : {sg['map_name']} (base game)")
    log("INFO", f"i3d      : {i3d_path}")

    with open(i3d_path, encoding="utf-8-sig", errors="ignore") as f:
        raw = f.read()

    if already_patched(raw) and not force:
        log("INFO", "Map is already patched — nothing to do.")
        return True, "already_patched"

    # Find blank GRLE template in game data directory
    blank = None
    grle_template = os.path.join(data_dir, "infoLayer_fieldType.grle")
    if os.path.exists(grle_template):
        with open(grle_template, "rb") as f:
            blank = f.read()
        log("DEBUG", f"GRLE template : {os.path.basename(grle_template)} ({len(blank):,} bytes)")
    else:
        # Fallback: any .grle in data dir
        if os.path.isdir(data_dir):
            for fn in sorted(os.listdir(data_dir)):
                if fn.endswith(".grle"):
                    with open(os.path.join(data_dir, fn), "rb") as f:
                        blank = f.read()
                    log("DEBUG", f"GRLE template (fallback): {fn} ({len(blank):,} bytes)")
                    break
    if blank is None:
        raise RuntimeError(
            f"Could not find a GRLE template in:\n{data_dir}\n\n"
            "Make sure the FS25 game installation path is correct in Settings.")

    # Backup i3d
    bp = i3d_path + ".backup_soilinstaller"
    if not os.path.exists(bp):
        shutil.copy2(i3d_path, bp)
        log("INFO", f"Backup   : {os.path.basename(bp)}")
    else:
        log("DEBUG", "Backup already exists — skipping.")

    # Patch
    max_fid = get_max_file_id(raw)
    log("DEBUG", f"Max existing fileId: {max_fid}")
    fe, le = [], []
    for idx, layer in enumerate(SOIL_LAYERS):
        fid  = max_fid + 1 + idx
        name = layer["name"]
        nc   = layer["numChannels"]
        fe.append((fid, f"data/infoLayer_{name}.grle"))
        le.append((name, fid, nc))

    log("INFO", f"Adding {len(SOIL_LAYERS)} layers (IDs {max_fid+1}–{max_fid+len(SOIL_LAYERS)}):")
    for name, fid, _ in le:
        log("INFO", f"  + {name}  (id={fid})")

    patched_i3d = patch_infolayer_section(patch_files_section(raw, fe), le)

    with open(i3d_path, "w", encoding="utf-8") as f:
        f.write(patched_i3d)
    log("DEBUG", "i3d updated.")

    # Write blank GRLE files
    os.makedirs(data_dir, exist_ok=True)
    for layer in SOIL_LAYERS:
        grle_path = os.path.join(data_dir, f"infoLayer_{layer['name']}.grle")
        with open(grle_path, "wb") as f:
            f.write(blank)
        log("DEBUG", f"  + {os.path.basename(grle_path)}")

    # Verify
    log("INFO", "Verifying…")
    ok = True
    with open(i3d_path, encoding="utf-8-sig", errors="ignore") as f:
        check = f.read()
    for layer in SOIL_LAYERS:
        n    = layer["name"]
        grle = os.path.join(data_dir, f"infoLayer_{n}.grle")
        good = (f'name="{n}"' in check) and os.path.exists(grle)
        log("INFO" if good else "ERROR", f"  [{'OK' if good else '!!'}] {n}")
        if not good:
            ok = False
    return ok, "patched"

# ── Mod-map installer (ZIP-based) ─────────────────────────────────────────────

def run_installer_zip(sg, log, force=False):
    log("INFO", f"Savegame : {sg['slot_name']}")
    log("INFO", f"Map ZIP  : {sg['zip_name']}")
    zip_path = sg["zip_path"]

    with zipfile.ZipFile(zip_path, "r") as z:
        i3d_path = find_i3d_path(z)
        if not i3d_path:
            raise RuntimeError("Could not find main .i3d file inside the map ZIP.")
        log("DEBUG", f"i3d file : {i3d_path}")
        raw = z.read(i3d_path).decode("utf-8-sig", errors="ignore")

        if already_patched(raw) and not force:
            log("INFO", "Map is already patched — nothing to do.")
            return True, "already_patched"

        if BLANK_GRLE_SOURCE not in z.namelist():
            raise RuntimeError(f"Template GRLE not found inside ZIP:\n{BLANK_GRLE_SOURCE}")
        blank    = z.read(BLANK_GRLE_SOURCE)
        log("DEBUG", f"GRLE template : {len(blank):,} bytes")
        snapshot = {item: z.read(item) for item in z.namelist()}

    bp = zip_path + ".backup_soilinstaller"
    if not os.path.exists(bp):
        shutil.copy2(zip_path, bp)
        log("INFO", f"Backup   : {os.path.basename(bp)}")
    else:
        log("DEBUG", "Backup already exists — skipping.")

    max_fid = get_max_file_id(raw)
    log("DEBUG", f"Max existing fileId: {max_fid}")
    fe, le, gf = [], [], {}
    for idx, layer in enumerate(SOIL_LAYERS):
        fid  = max_fid + 1 + idx
        name = layer["name"]
        nc   = layer["numChannels"]
        fe.append((fid, f"data/infoLayer_{name}.grle"))
        le.append((name, fid, nc))
        gf[f"maps/data/infoLayer_{name}.grle"] = blank

    log("INFO", f"Adding {len(SOIL_LAYERS)} layers (IDs {max_fid+1}–{max_fid+len(SOIL_LAYERS)}):")
    for name, fid, _ in le:
        log("INFO", f"  + {name}  (id={fid})")

    patched_i3d = patch_infolayer_section(patch_files_section(raw, fe), le)

    log("INFO", "Repacking ZIP…")
    tmp = zip_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
        for p, d in snapshot.items():
            zout.writestr(p, patched_i3d.encode("utf-8") if p == i3d_path else d)
        for p, d in gf.items():
            zout.writestr(p, d)
    os.replace(tmp, zip_path)
    log("DEBUG", "ZIP replaced successfully.")

    log("INFO", "Verifying…")
    ok = True
    with zipfile.ZipFile(zip_path, "r") as z:
        check = z.read(i3d_path).decode("utf-8-sig", errors="ignore")
        names = z.namelist()
        for layer in SOIL_LAYERS:
            n    = layer["name"]
            grle = f"maps/data/infoLayer_{n}.grle"
            good = (f'name="{n}"' in check) and (grle in names)
            log("INFO" if good else "ERROR", f"  [{'OK' if good else '!!'}] {n}")
            if not good:
                ok = False
    return ok, "patched"

# ── Dispatcher ────────────────────────────────────────────────────────────────

def run_installer(sg, log, force=False):
    if sg.get("is_base_game"):
        return run_installer_base_game(sg, log, force)
    if not sg["zip_path"]:
        raise RuntimeError(
            f"Map ZIP not found for '{sg['map_id']}'.\n\n"
            "Make sure the map mod is installed in your Mods folder.")
    return run_installer_zip(sg, log, force)


# ── GUI Application ────────────────────────────────────────────────────────────

class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"FS25 Soil Layer Installer  v{APP_VERSION}")
        self.resizable(True, True)
        self.minsize(640, 580)
        self.configure(bg=BG)

        # Runtime state
        self._saves_dir = DEF_SAVES
        self._mods_dir  = DEF_MODS
        self._game_dir  = DEF_GAME_DIR
        self._savegames = []
        self._selected  = None
        self._scanning  = False
        self._running   = False

        # Settings vars
        self._debug_on     = tk.BooleanVar(value=False)
        self._force_patch  = tk.BooleanVar(value=False)
        self._ov_saves     = tk.BooleanVar(value=False)
        self._ov_mods      = tk.BooleanVar(value=False)
        self._ov_game      = tk.BooleanVar(value=False)
        self._custom_saves = tk.StringVar(value=DEF_SAVES)
        self._custom_mods  = tk.StringVar(value=DEF_MODS)
        self._custom_game  = tk.StringVar(value=DEF_GAME_DIR or "")

        self._setup_style()
        self._build_ui()
        self.after(300, self._do_scan)

    # ── ttk Style ─────────────────────────────────────────────────────────────

    def _setup_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")

        s.configure("TNotebook", background=BG, borderwidth=0,
                    tabmargins=[0, 6, 0, 0])
        s.configure("TNotebook.Tab", background=PANEL, foreground=DIM,
                    padding=[22, 9], font=("Segoe UI", 10), borderwidth=0)
        s.map("TNotebook.Tab",
              background=[("selected", BG), ("active", OVERLAY)],
              foreground=[("selected", TEXT), ("active", SUBTEXT)])

        s.configure("Treeview", background=SURFACE, foreground=TEXT,
                    fieldbackground=SURFACE, borderwidth=0, rowheight=32,
                    font=("Segoe UI", 10))
        s.configure("Treeview.Heading", background=OVERLAY, foreground=SUBTEXT,
                    borderwidth=0, font=("Segoe UI", 9, "bold"),
                    relief="flat", padding=[10, 7])
        s.map("Treeview",
              background=[("selected", OVERLAY)],
              foreground=[("selected", TEXT)])

        s.configure("Green.Horizontal.TProgressbar",
                    troughcolor=SURFACE, background=GREEN,
                    borderwidth=0, thickness=5)
        s.configure("TSeparator", background=BORDER)
        s.configure("TCheckbutton", background=PANEL, foreground=TEXT,
                    font=("Segoe UI", 10))
        s.map("TCheckbutton",
              background=[("active", PANEL)],
              indicatorcolor=[("selected", GREEN), ("!selected", OVERLAY)])

    # ── Top-level layout ──────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True)
        self._build_tab_installer()
        self._build_tab_settings()
        self._build_tab_log()
        self._build_statusbar()

    def _build_header(self):
        hf = tk.Frame(self, bg=PANEL, height=62)
        hf.pack(fill="x")
        hf.pack_propagate(False)
        inner = tk.Frame(hf, bg=PANEL)
        inner.pack(side="left", padx=20, pady=0, fill="y")
        tk.Label(inner, text="FS25  Soil Layer Installer", font=H1,
                 bg=PANEL, fg=GREEN).pack(anchor="sw", pady=(14, 0))
        tk.Label(inner, text="Adds per-pixel soil tracking to any FS25 map mod",
                 font=SM, bg=PANEL, fg=DIM).pack(anchor="nw")
        tk.Label(hf, text=f"v{APP_VERSION}", font=("Segoe UI", 9),
                 bg=PANEL, fg=DIM).pack(side="right", padx=20, anchor="s", pady=14)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

    # ── Tab 1: Installer ──────────────────────────────────────────────────────

    def _build_tab_installer(self):
        tab = tk.Frame(self._nb, bg=BG)
        self._nb.add(tab, text="  Installer  ")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        # Scanner header row
        sh = tk.Frame(tab, bg=BG)
        sh.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        tk.Label(sh, text="Savegames", font=H2, bg=BG, fg=TEXT).pack(side="left")
        self._btn_scan = tk.Button(sh, text="↺  Rescan",
            font=SM, bg=OVERLAY, fg=SUBTEXT,
            activebackground=BORDER, activeforeground=TEXT,
            relief="flat", cursor="hand2", padx=10, pady=5,
            command=self._do_scan)
        self._btn_scan.pack(side="right")

        # Treeview
        tf = tk.Frame(tab, bg=SURFACE,
                      highlightthickness=1, highlightbackground=BORDER)
        tf.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 0))
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)

        cols = ("slot", "map", "status")
        self._tree = ttk.Treeview(tf, columns=cols, show="headings",
                                   selectmode="browse")
        self._tree.heading("slot",   text="Slot",   anchor="w")
        self._tree.heading("map",    text="Map",    anchor="w")
        self._tree.heading("status", text="Status", anchor="center")
        self._tree.column("slot",   width=115, minwidth=90,  stretch=False, anchor="w")
        self._tree.column("map",    width=280, minwidth=140, stretch=True,  anchor="w")
        self._tree.column("status", width=130, minwidth=100, stretch=False, anchor="center")

        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._tree.tag_configure("patched",   foreground=GREEN)
        self._tree.tag_configure("ready",     foreground=BLUE)
        self._tree.tag_configure("no_zip",    foreground=YELLOW)
        self._tree.tag_configure("base_game", foreground=BLUE)
        self._tree.tag_configure("unknown",   foreground=DIM)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # Info card
        self._info_frame = tk.Frame(tab, bg=PANEL, padx=16, pady=10)
        self._info_frame.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 0))
        self._info_frame.columnconfigure(1, weight=1)
        self._info_placeholder = tk.Label(self._info_frame,
            text="Select a savegame above to see details.",
            font=BD, bg=PANEL, fg=DIM)
        self._info_placeholder.grid(row=0, column=0, columnspan=3, pady=6)

        # Progress bar + Run button
        bf = tk.Frame(tab, bg=BG)
        bf.grid(row=3, column=0, sticky="ew", padx=18, pady=(10, 16))
        bf.columnconfigure(0, weight=1)

        self._progress = ttk.Progressbar(bf, mode="indeterminate",
                                          style="Green.Horizontal.TProgressbar")
        self._progress.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._progress.grid_remove()

        self._btn_run = tk.Button(bf, text="Run Installer",
            font=BT, bg=DIM, fg=BG,
            activebackground=GREEN, activeforeground=BG,
            relief="flat", pady=13,
            state="disabled", command=self._on_run)
        self._btn_run.grid(row=1, column=0, sticky="ew")

    # ── Tab 2: Settings ───────────────────────────────────────────────────────

    def _build_tab_settings(self):
        tab = tk.Frame(self._nb, bg=BG)
        self._nb.add(tab, text="  Settings  ")
        tab.columnconfigure(0, weight=1)

        r = 0
        pad = dict(padx=18, pady=5)

        # Detected paths (read-only)
        tk.Label(tab, text="Auto-Detected Paths", font=H2,
                 bg=BG, fg=TEXT).grid(row=r, column=0, sticky="w",
                                       padx=18, pady=(16, 4))
        r += 1
        pf = tk.Frame(tab, bg=PANEL, padx=14, pady=10)
        pf.grid(row=r, column=0, sticky="ew", **pad)
        pf.columnconfigure(1, weight=1)

        def _short(p, n=52):
            return p if len(p) <= n else "…" + p[-n+1:] if p else "Not detected"

        game_disp = _short(DEF_GAME_DIR) if DEF_GAME_DIR else "Not detected"
        game_color = TEXT if DEF_GAME_DIR else YELLOW
        path_rows = [
            ("Documents :", _short(DOCS),         TEXT),
            ("Saves dir :", _short(DEF_SAVES),     TEXT),
            ("Mods dir  :", _short(DEF_MODS),      TEXT),
            ("Game dir  :", game_disp,              game_color),
        ]
        for i, (lbl, val, col) in enumerate(path_rows):
            tk.Label(pf, text=lbl, font=H3, bg=PANEL, fg=SUBTEXT,
                     anchor="e", width=13).grid(row=i, column=0, sticky="e", pady=3)
            tk.Label(pf, text=val, font=SM, bg=PANEL, fg=col,
                     anchor="w").grid(row=i, column=1, sticky="w", padx=8)
        r += 1

        # Override paths
        tk.Label(tab, text="Override Paths", font=H2,
                 bg=BG, fg=TEXT).grid(row=r, column=0, sticky="w",
                                       padx=18, pady=(10, 4))
        r += 1
        of = tk.Frame(tab, bg=PANEL, padx=14, pady=10)
        of.grid(row=r, column=0, sticky="ew", **pad)
        of.columnconfigure(0, weight=1)

        def _make_override(parent, row_cb, row_entry, label, sv, ov_var, browse_key):
            entry = tk.Entry(parent, textvariable=sv,
                font=SM, bg=SURFACE, fg=DIM, insertbackground=TEXT,
                relief="flat", state="disabled",
                disabledbackground=SURFACE, disabledforeground=DIM)
            btn = tk.Button(parent, text="Browse", font=SM,
                bg=OVERLAY, fg=DIM, activebackground=BORDER,
                relief="flat", state="disabled", padx=8, pady=4,
                command=lambda: self._browse(browse_key))
            ttk.Checkbutton(parent, text=f"  {label}",
                            variable=ov_var,
                            command=lambda: self._toggle_override(ov_var, entry, btn)
                            ).grid(row=row_cb, column=0, columnspan=2,
                                   sticky="w", pady=(4, 2))
            entry.grid(row=row_entry, column=0, sticky="ew", ipady=5, pady=(0, 8))
            btn.grid(row=row_entry, column=1, sticky="w", padx=(6, 0), pady=(0, 8))
            return entry, btn

        self._saves_entry, self._saves_browse_btn = _make_override(
            of, 0, 1, "Override Saves directory",
            self._custom_saves, self._ov_saves, "saves")
        self._mods_entry, self._mods_browse_btn = _make_override(
            of, 2, 3, "Override Mods directory",
            self._custom_mods, self._ov_mods, "mods")
        self._game_entry, self._game_browse_btn = _make_override(
            of, 4, 5, "Override Game installation directory",
            self._custom_game, self._ov_game, "game")
        r += 1

        # Options
        tk.Label(tab, text="Options", font=H2,
                 bg=BG, fg=TEXT).grid(row=r, column=0, sticky="w",
                                       padx=18, pady=(10, 4))
        r += 1
        opt = tk.Frame(tab, bg=PANEL, padx=14, pady=10)
        opt.grid(row=r, column=0, sticky="ew", **pad)

        ttk.Checkbutton(opt,
            text="  Debug / verbose logging  —  shows extra detail in the Log tab",
            variable=self._debug_on).pack(anchor="w", pady=4)
        ttk.Checkbutton(opt,
            text="  Force re-patch  —  allow patching an already-patched map",
            variable=self._force_patch,
            command=self._refresh_run_btn).pack(anchor="w", pady=4)
        r += 1

        # Apply button
        tk.Button(tab, text="Apply & Re-scan",
            font=("Segoe UI", 10, "bold"), bg=BLUE, fg=BG,
            activebackground="#7aa2f7", activeforeground=BG,
            relief="flat", cursor="hand2", pady=11,
            command=self._apply_settings
        ).grid(row=r, column=0, sticky="ew", padx=18, pady=(10, 20))

    # ── Tab 3: Log ────────────────────────────────────────────────────────────

    def _build_tab_log(self):
        tab = tk.Frame(self._nb, bg=BG)
        self._nb.add(tab, text="  Log  ")
        tab.rowconfigure(1, weight=1)
        tab.columnconfigure(0, weight=1)

        tb = tk.Frame(tab, bg=PANEL, pady=7)
        tb.grid(row=0, column=0, columnspan=2, sticky="ew")
        for txt, cmd in [("Copy All", self._log_copy),
                          ("Save to File", self._log_save),
                          ("Clear", self._log_clear)]:
            tk.Button(tb, text=txt, font=SM,
                      bg=OVERLAY, fg=SUBTEXT,
                      activebackground=BORDER, activeforeground=TEXT,
                      relief="flat", cursor="hand2", padx=12, pady=4,
                      command=cmd).pack(side="left", padx=(10, 0))
        tk.Label(tb, text="Debug messages shown only when Debug is ON in Settings.",
                 font=SM, bg=PANEL, fg=DIM).pack(side="right", padx=12)
        tk.Frame(tab, bg=BORDER, height=1).grid(row=0, column=0,
                                                  columnspan=2, sticky="sew")

        self._log_txt = tk.Text(tab, font=MN, bg=SURFACE, fg=TEXT,
                                 insertbackground=TEXT, relief="flat",
                                 state="disabled", wrap="word",
                                 borderwidth=0, padx=12, pady=10)
        vsb = ttk.Scrollbar(tab, orient="vertical", command=self._log_txt.yview)
        self._log_txt.configure(yscrollcommand=vsb.set)
        self._log_txt.grid(row=1, column=0, sticky="nsew")
        vsb.grid(row=1, column=1, sticky="ns")

        self._log_txt.tag_configure("ts",      foreground=DIM)
        self._log_txt.tag_configure("DEBUG",   foreground=DIM)
        self._log_txt.tag_configure("INFO",    foreground=TEXT)
        self._log_txt.tag_configure("WARNING", foreground=YELLOW)
        self._log_txt.tag_configure("ERROR",   foreground=RED)
        self._log_txt.tag_configure("OK",      foreground=GREEN)

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_statusbar(self):
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        sb = tk.Frame(self, bg=PANEL, height=28)
        sb.pack(fill="x")
        sb.pack_propagate(False)
        self._sb_dot = tk.Label(sb, text="●", font=("Segoe UI", 10),
                                 bg=PANEL, fg=DIM)
        self._sb_dot.pack(side="left", padx=(10, 4), pady=0)
        self._sb_lbl = tk.Label(sb, text="Starting…", font=SM,
                                 bg=PANEL, fg=SUBTEXT)
        self._sb_lbl.pack(side="left")
        short = DOCS if len(DOCS) <= 48 else "…" + DOCS[-45:]
        tk.Label(sb, text=f"Docs: {short}", font=SM,
                 bg=PANEL, fg=DIM).pack(side="right", padx=12)

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log(self, level, msg):
        if level == "DEBUG" and not self._debug_on.get():
            return
        ts  = datetime.datetime.now().strftime("%H:%M:%S")
        tag = "OK" if "[OK]" in msg else level
        self._log_txt.configure(state="normal")
        self._log_txt.insert("end", ts + "  ", "ts")
        self._log_txt.insert("end", f"{level:<8}", tag)
        self._log_txt.insert("end", msg + "\n", tag)
        self._log_txt.see("end")
        self._log_txt.configure(state="disabled")

    def _set_status(self, msg, color=DIM):
        self._sb_lbl.config(text=msg, fg=color)
        self._sb_dot.config(fg=color)

    def _log_copy(self):
        self.clipboard_clear()
        self.clipboard_append(self._log_txt.get("1.0", "end"))

    def _log_save(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile="soil_installer_log.txt")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._log_txt.get("1.0", "end"))

    def _log_clear(self):
        self._log_txt.configure(state="normal")
        self._log_txt.delete("1.0", "end")
        self._log_txt.configure(state="disabled")

    # ── Treeview helpers ──────────────────────────────────────────────────────

    def _status_for(self, sg):
        """Return (display_string, tag_name) for a savegame dict."""
        if sg["patched"] is True:
            return ("✓  Patched", "patched")
        if sg.get("is_base_game"):
            return ("○  Ready",   "base_game")
        if sg["zip_path"] is not None and sg["patched"] is False:
            return ("○  Ready",   "ready")
        if sg["zip_path"] is None and not sg.get("is_base_game"):
            return ("✗  No ZIP",  "no_zip")
        return ("?  Unknown", "unknown")

    def _populate_tree(self, savegames):
        for item in self._tree.get_children():
            self._tree.delete(item)
        if not savegames:
            self._tree.insert("", "end", iid="empty",
                               values=("—", "No savegames found", "—"),
                               tags=("unknown",))
            return
        for sg in savegames:
            status_str, tag = self._status_for(sg)
            self._tree.insert("", "end", iid=str(sg["slot"]),
                               values=(sg["slot_name"], sg["map_name"], status_str),
                               tags=(tag,))

    def _on_tree_select(self, _event=None):
        sel = self._tree.selection()
        if not sel or sel[0] == "empty":
            self._selected = None
            self._update_info_card(None)
            self._refresh_run_btn()
            return
        try:
            slot = int(sel[0])
        except ValueError:
            return
        self._selected = next((s for s in self._savegames if s["slot"] == slot), None)
        self._update_info_card(self._selected)
        self._refresh_run_btn()

    def _update_info_card(self, sg):
        for w in self._info_frame.winfo_children():
            w.destroy()
        self._info_frame.columnconfigure(1, weight=1)

        if sg is None:
            tk.Label(self._info_frame,
                     text="Select a savegame above to see details.",
                     font=BD, bg=PANEL, fg=DIM
                     ).grid(row=0, column=0, columnspan=3, pady=6)
            return

        status_str, _ = self._status_for(sg)

        if sg.get("is_base_game"):
            # Base game map — show i3d path instead of ZIP
            i3d_short = sg["game_i3d"]
            if i3d_short and len(i3d_short) > 52:
                i3d_short = "…" + i3d_short[-51:]
            rows = [
                ("Slot",   sg["slot_name"],                    TEXT),
                ("Map",    sg["map_name"],                     TEXT),
                ("Type",   "Base Game Map",                    BLUE),
                ("i3d",    i3d_short or "Not found",
                           TEXT if sg["game_i3d"] else RED),
                ("Status", status_str.strip(),
                           GREEN if sg["patched"] else BLUE),
                ("Backup", "✓ Backup exists" if sg["has_backup"] else "None yet",
                           GREEN if sg["has_backup"] else DIM),
            ]
        else:
            rows = [
                ("Slot",   sg["slot_name"],                                       TEXT),
                ("Map",    sg["map_name"],                                        TEXT),
                ("ZIP",    sg["zip_name"] or "Not found in Mods folder",
                           YELLOW if not sg["zip_path"] else TEXT),
                ("Status", status_str.strip(),
                           GREEN if sg["patched"] else BLUE if sg["zip_path"] else YELLOW),
                ("Backup", "✓ Backup exists" if sg["has_backup"] else "None yet",
                           GREEN if sg["has_backup"] else DIM),
            ]

        for i, (label, value, color) in enumerate(rows):
            tk.Label(self._info_frame, text=f"{label}:", font=H3,
                     bg=PANEL, fg=SUBTEXT, anchor="e", width=8
                     ).grid(row=i, column=0, sticky="e", pady=2, padx=(0, 10))
            tk.Label(self._info_frame, text=value, font=BD,
                     bg=PANEL, fg=color, anchor="w"
                     ).grid(row=i, column=1, sticky="w")

        if sg["has_backup"] and sg["backup_path"]:
            tk.Button(self._info_frame, text="Restore Backup",
                font=SM, bg=OVERLAY, fg=YELLOW,
                activebackground=BORDER, activeforeground=YELLOW,
                relief="flat", cursor="hand2", padx=10, pady=4,
                command=self._restore_backup
            ).grid(row=len(rows), column=0, columnspan=2,
                   sticky="w", pady=(10, 2))

    def _refresh_run_btn(self):
        sg = self._selected
        if sg is None or self._running or self._scanning:
            self._btn_run.config(state="disabled", bg=DIM, fg=BG,
                                  text="Run Installer", cursor="arrow")
            return
        can_run = sg["zip_path"] is not None or sg.get("is_base_game")
        if not can_run:
            self._btn_run.config(state="disabled", bg=DIM, fg=BG,
                                  text="✗  Map ZIP Not Found", cursor="arrow")
            return
        if sg["patched"] and not self._force_patch.get():
            self._btn_run.config(state="disabled", bg=DIM, fg=BG,
                                  text="✓  Already Patched", cursor="arrow")
            return
        if sg["patched"] and self._force_patch.get():
            self._btn_run.config(state="normal", bg=YELLOW, fg=BG,
                                  text="⚠  Force Re-patch", cursor="hand2")
            return
        self._btn_run.config(state="normal", bg=GREEN, fg=BG,
                              text="Run Installer", cursor="hand2")

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _do_scan(self):
        if self._scanning or self._running:
            return
        self._scanning = True
        self._btn_scan.config(state="disabled")
        self._selected = None
        self._update_info_card(None)
        self._refresh_run_btn()
        self._set_status("Scanning savegames…", BLUE)
        self._log("INFO", f"Scanning  saves: {self._saves_dir}")
        self._log("INFO", f"          mods:  {self._mods_dir}")
        self._log("INFO", f"          game:  {self._game_dir or 'Not detected'}")
        for item in self._tree.get_children():
            self._tree.delete(item)
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            results = scan_savegames(
                self._saves_dir, self._mods_dir, self._game_dir, self._log)
            self.after(0, self._scan_done, results, None)
        except Exception as e:
            self.after(0, self._scan_done, [], str(e))

    def _scan_done(self, results, error):
        self._scanning = False
        self._btn_scan.config(state="normal")
        self._savegames = results

        if error:
            self._log("ERROR", f"Scan failed: {error}")
            self._set_status(f"Scan error — {error}", RED)
        else:
            ready = sum(1 for s in results
                        if not s["patched"] and (s["zip_path"] or s.get("is_base_game")))
            done  = sum(1 for s in results if s["patched"] is True)
            self._log("INFO", f"Found {len(results)} savegame(s) — "
                               f"{ready} ready to patch, {done} already patched")
            if not results:
                self._set_status(
                    "No savegames found — start a career in FS25 first.", YELLOW)
            else:
                self._set_status(
                    f"Found {len(results)} savegame(s) — "
                    f"{ready} ready, {done} patched.",
                    GREEN if ready > 0 else DIM)

        self._populate_tree(results)

        # Auto-select first save that is ready to patch
        for sg in results:
            if not sg["patched"] and (sg["zip_path"] or sg.get("is_base_game")):
                self._tree.selection_set(str(sg["slot"]))
                self._tree.focus(str(sg["slot"]))
                self._on_tree_select()
                return

        self._refresh_run_btn()

    # ── Install ───────────────────────────────────────────────────────────────

    def _on_run(self):
        if not self._selected:
            return
        self._running = True
        self._refresh_run_btn()
        self._btn_run.config(text="Installing…", bg=DIM, state="disabled")
        self._progress.grid()
        self._progress.start(12)
        self._set_status("Installing…", YELLOW)
        self._log("INFO", "─" * 52)
        self._log("INFO", "Starting installer…")
        self._nb.select(2)
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self):
        try:
            ok, result = run_installer(
                self._selected, self._log, force=self._force_patch.get())
            self.after(0, self._install_done, ok, result)
        except Exception as e:
            self.after(0, self._install_error, str(e))

    def _install_done(self, ok, result):
        self._running = False
        self._progress.stop()
        self._progress.grid_remove()

        if result == "already_patched":
            self._set_status("Already patched — nothing changed.", DIM)
            messagebox.showinfo("Nothing to do",
                "This map is already patched!\n\nYou can load your savegame right now.")
        elif ok:
            self._log("OK", "Patch applied successfully!")
            self._set_status("Patch applied. Launch FS25 and load your save.", GREEN)
            messagebox.showinfo("All done!",
                "5 soil layers added to your map.\n\n"
                "Launch Farming Simulator 25 and load your save.\n"
                "FS25_SoilFertilizer detects the new layers automatically.")
        else:
            self._log("ERROR", "Partial success — some layers may be missing.")
            self._set_status("Partial success — check the Log tab.", ORANGE)
            messagebox.showwarning("Partial success",
                "Some layers may not have been applied correctly.\n\n"
                "Check the Log tab for details.\n"
                "Your original map was backed up before any changes.")

        self.after(400, self._do_scan)

    def _install_error(self, msg):
        self._running = False
        self._progress.stop()
        self._progress.grid_remove()
        self._log("ERROR", f"Install failed: {msg}")
        self._set_status("Error — see Log tab.", RED)
        self._refresh_run_btn()
        messagebox.showerror("Error", msg)

    # ── Restore backup ────────────────────────────────────────────────────────

    def _restore_backup(self):
        sg = self._selected
        if not sg or not sg["has_backup"] or not sg["backup_path"]:
            return
        target = sg["game_i3d"] if sg.get("is_base_game") else sg["zip_path"]
        label  = os.path.basename(sg["backup_path"])
        if not messagebox.askyesno("Restore Backup",
                f"Restore the backup:\n{label}\n\n"
                "This will undo the soil layer patch. Continue?"):
            return
        try:
            shutil.copy2(sg["backup_path"], target)
            self._log("INFO", f"Restored backup: {label}")
            self._set_status("Backup restored successfully.", BLUE)
        except Exception as e:
            self._log("ERROR", f"Restore failed: {e}")
            messagebox.showerror("Restore failed", str(e))
            return
        self.after(400, self._do_scan)

    # ── Settings helpers ──────────────────────────────────────────────────────

    def _toggle_override(self, var, entry, btn):
        state = "normal" if var.get() else "disabled"
        fg    = TEXT if var.get() else DIM
        entry.config(state=state, fg=fg, disabledforeground=DIM)
        btn.config(state=state, fg=fg if var.get() else DIM)

    def _browse(self, key):
        titles = {"saves": "Select Saves directory",
                  "mods":  "Select Mods directory",
                  "game":  "Select FS25 game installation directory"}
        path = filedialog.askdirectory(title=titles.get(key, "Select directory"))
        if path:
            {"saves": self._custom_saves,
             "mods":  self._custom_mods,
             "game":  self._custom_game}[key].set(path)

    def _apply_settings(self):
        self._saves_dir = (self._custom_saves.get()
                           if self._ov_saves.get() else DEF_SAVES)
        self._mods_dir  = (self._custom_mods.get()
                           if self._ov_mods.get()  else DEF_MODS)
        self._game_dir  = (self._custom_game.get()
                           if self._ov_game.get()  else DEF_GAME_DIR)
        self._log("INFO", "Settings applied.")
        self._log("INFO", f"  Saves dir: {self._saves_dir}")
        self._log("INFO", f"  Mods dir:  {self._mods_dir}")
        self._log("INFO", f"  Game dir:  {self._game_dir or 'Not set'}")
        self._nb.select(0)
        self._do_scan()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = InstallerApp()
    app.mainloop()
