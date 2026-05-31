#!/usr/bin/env python3
"""
FS25 SoilFertilizer — Soil Layer Installer (GUI)
Double-click to run. No Python knowledge needed.
"""

import os, re, shutil, zipfile, threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

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
    # Fallback: standard location (works when OneDrive is not involved)
    return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Documents")

_DOCS    = _get_documents_dir()
MODS_DIR  = os.path.join(_DOCS, "My Games", "FarmingSimulator2025", "mods")
SAVES_DIR = os.path.join(_DOCS, "My Games", "FarmingSimulator2025")

SOIL_LAYERS = [
    {"name": "soilN",  "numChannels": 8},
    {"name": "soilP",  "numChannels": 8},
    {"name": "soilK",  "numChannels": 8},
    {"name": "soilPH", "numChannels": 8},
    {"name": "soilOM", "numChannels": 8},
]
BLANK_GRLE_SOURCE = "maps/data/infoLayer_fieldType.grle"

# ─── Core installer logic ──────────────────────────────────────────────────────

def find_savegame():
    for i in range(1, 21):
        path = os.path.join(SAVES_DIR, f"savegame{i}", "careerSavegame.xml")
        if os.path.exists(path):
            return os.path.dirname(path)
    return None

def find_map_id(savegame_dir):
    career = os.path.join(savegame_dir, "careerSavegame.xml")
    with open(career, encoding="utf-8-sig", errors="ignore") as f:
        content = f.read()
    m = re.search(r"<mapId>([^<]+)</mapId>", content)
    return m.group(1) if m else None

def find_map_zip(map_id):
    mod_name = map_id.split(".")[0]
    zip_path = os.path.join(MODS_DIR, mod_name + ".zip")
    if os.path.exists(zip_path):
        return zip_path
    for f in os.listdir(MODS_DIR):
        if f.lower() == (mod_name + ".zip").lower():
            return os.path.join(MODS_DIR, f)
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

def run_installer(log):
    """Run the full install. log(msg) writes to the GUI log area."""

    log("Scanning for active savegame...")
    savegame_dir = find_savegame()
    if not savegame_dir:
        raise RuntimeError("No savegame found in:\n" + SAVES_DIR
                           + "\n\nMake sure you have at least one career save.")
    sg_name = os.path.basename(savegame_dir)
    log(f"  Savegame : {sg_name}")

    map_id = find_map_id(savegame_dir)
    if not map_id:
        raise RuntimeError("Could not read mapId from careerSavegame.xml.")
    log(f"  Map ID   : {map_id}")

    zip_path = find_map_zip(map_id)
    if not zip_path:
        raise RuntimeError(
            f"Map ZIP not found for '{map_id}'.\n\nMake sure the map mod is installed in:\n{MODS_DIR}")
    log(f"  Map ZIP  : {os.path.basename(zip_path)}")

    with zipfile.ZipFile(zip_path, "r") as z:
        i3d_path = find_i3d_path(z)
        if not i3d_path:
            raise RuntimeError("Could not find the main .i3d file inside the map ZIP.")
        log(f"  i3d file : {i3d_path}")
        i3d_content = z.read(i3d_path).decode("utf-8-sig", errors="ignore")

        if already_patched(i3d_content):
            log("\nThis map is already patched — nothing to do!")
            log("You can load your savegame right now.")
            return True, "already_patched"

        if BLANK_GRLE_SOURCE not in z.namelist():
            raise RuntimeError(f"Blank GRLE template not found inside ZIP:\n{BLANK_GRLE_SOURCE}")
        blank_grle = z.read(BLANK_GRLE_SOURCE)
        log(f"\n  GRLE template: {len(blank_grle):,} bytes")

        existing_files = {item: z.read(item) for item in z.namelist()}

    backup_path = zip_path + ".backup_soilinstaller"
    if not os.path.exists(backup_path):
        shutil.copy2(zip_path, backup_path)
        log(f"  Backup created: {os.path.basename(backup_path)}")
    else:
        log("  Backup already exists — skipping.")

    max_fid = get_max_file_id(i3d_content)
    new_file_entries, new_layer_entries, new_grle_files = [], [], {}
    for i, layer in enumerate(SOIL_LAYERS):
        fid  = max_fid + 1 + i
        name = layer["name"]
        nc   = layer["numChannels"]
        grle_zip_path = f"maps/data/infoLayer_{name}.grle"
        i3d_rel_path  = f"data/infoLayer_{name}.grle"
        new_file_entries.append((fid, i3d_rel_path))
        new_layer_entries.append((name, fid, nc))
        new_grle_files[grle_zip_path] = blank_grle

    log(f"\n  Adding layers (fileIds {max_fid+1}-{max_fid+len(SOIL_LAYERS)}):")
    for name, fid, _ in new_layer_entries:
        log(f"    + {name}  (id={fid})")

    patched_i3d = patch_files_section(i3d_content, new_file_entries)
    patched_i3d = patch_infolayer_section(patched_i3d, new_layer_entries)

    log("\n  Repacking map ZIP...")
    tmp_path = zip_path + ".tmp"
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
        for item_path, data in existing_files.items():
            zout.writestr(item_path, patched_i3d.encode("utf-8") if item_path == i3d_path else data)
        for grle_path, data in new_grle_files.items():
            zout.writestr(grle_path, data)
    os.replace(tmp_path, zip_path)

    log("\n  Verifying patch...")
    ok = True
    with zipfile.ZipFile(zip_path, "r") as z:
        check = z.read(i3d_path).decode("utf-8-sig", errors="ignore")
        for layer in SOIL_LAYERS:
            name  = layer["name"]
            grle  = f"maps/data/infoLayer_{name}.grle"
            n_ok  = f'name="{name}"' in check
            g_ok  = grle in z.namelist()
            mark  = "OK" if (n_ok and g_ok) else "!!"
            log(f"    [{mark}] {name}")
            if not (n_ok and g_ok):
                ok = False

    return ok, "patched"

# ─── GUI ──────────────────────────────────────────────────────────────────────

DARK_BG   = "#1e1e2e"
PANEL_BG  = "#2a2a3e"
ACCENT    = "#a6e3a1"   # green
TEXT_FG   = "#cdd6f4"
DIM_FG    = "#6c7086"
ERR_FG    = "#f38ba8"   # red
FONT_BODY = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 9)
FONT_H1   = ("Segoe UI", 13, "bold")
FONT_H2   = ("Segoe UI", 10, "bold")

class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FS25 Soil Layer Installer")
        self.resizable(False, False)
        self.configure(bg=DARK_BG)
        try:
            self.iconbitmap(default="")
        except Exception:
            pass
        self._build_ui()
        self.after(100, self._scan)

    def _build_ui(self):
        pad = dict(padx=18, pady=6)

        # ── Header ──
        hdr = tk.Frame(self, bg=DARK_BG)
        hdr.pack(fill="x", padx=18, pady=(18, 4))
        tk.Label(hdr, text="FS25  Soil Layer Installer", font=FONT_H1,
                 bg=DARK_BG, fg=ACCENT).pack(anchor="w")
        tk.Label(hdr, text="Adds per-pixel nutrient tracking to your map mod.",
                 font=FONT_BODY, bg=DARK_BG, fg=DIM_FG).pack(anchor="w")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=18, pady=6)

        # ── Info cards ──
        cards = tk.Frame(self, bg=DARK_BG)
        cards.pack(fill="x", **pad)
        self._card(cards, "What it does",
            "Patches your active map mod ZIP to add 5 soil info layers\n"
            "(N, P, K, pH, Organic Matter). FS25_SoilFertilizer uses\n"
            "these for a real per-pixel heatmap instead of field averages.")
        self._card(cards, "What it checks",
            "• Your active savegame folder\n"
            "• The map mod that savegame uses\n"
            "• Whether the patch has already been applied")
        self._card(cards, "What it writes",
            "• Your map mod ZIP  (a backup is created first)\n"
            "• Five blank GRLE data files inside the ZIP\n"
            "• Nothing else — no registry, no settings files")
        self._card(cards, "After running",
            "Launch Farming Simulator 25 and load your save.\n"
            "The mod detects the new layers automatically.\n"
            "No extra steps needed.")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=18, pady=6)

        # ── Status line ──
        sf = tk.Frame(self, bg=DARK_BG)
        sf.pack(fill="x", padx=18, pady=(0, 4))
        tk.Label(sf, text="Status:", font=FONT_H2, bg=DARK_BG, fg=TEXT_FG).pack(side="left")
        self._status_var = tk.StringVar(value="Scanning…")
        tk.Label(sf, textvariable=self._status_var, font=FONT_BODY,
                 bg=DARK_BG, fg=DIM_FG).pack(side="left", padx=(6, 0))

        # ── Log box ──
        self._log = scrolledtext.ScrolledText(
            self, height=10, font=FONT_MONO, bg=PANEL_BG, fg=TEXT_FG,
            insertbackground=TEXT_FG, relief="flat", state="disabled",
            wrap="word", borderwidth=0, highlightthickness=1,
            highlightbackground=PANEL_BG)
        self._log.pack(fill="x", padx=18, pady=(0, 8))

        # ── Run button ──
        self._btn = tk.Button(
            self, text="Run Installer",
            font=("Segoe UI", 12, "bold"),
            bg=ACCENT, fg="#1e1e2e", activebackground="#94d3a2",
            relief="flat", cursor="hand2", pady=10,
            command=self._on_run)
        self._btn.pack(fill="x", padx=18, pady=(0, 18))

    def _card(self, parent, title, body):
        frame = tk.Frame(parent, bg=PANEL_BG, padx=12, pady=8)
        frame.pack(fill="x", pady=4)
        tk.Label(frame, text=title, font=FONT_H2, bg=PANEL_BG, fg=ACCENT).pack(anchor="w")
        tk.Label(frame, text=body, font=FONT_BODY, bg=PANEL_BG, fg=TEXT_FG,
                 justify="left").pack(anchor="w")

    def _log_append(self, msg):
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_status(self, msg, color=DIM_FG):
        self._status_var.set(msg)
        for w in self.winfo_children():
            if isinstance(w, tk.Frame):
                for c in w.winfo_children():
                    if isinstance(c, tk.Label) and c.cget("textvariable") == str(self._status_var):
                        c.configure(fg=color)

    def _scan(self):
        sg = find_savegame()
        if not sg:
            self._set_status("No savegame found — start a career first.", ERR_FG)
            self._btn.configure(state="disabled", bg="#555")
            return
        mid = find_map_id(sg)
        if not mid:
            self._set_status("Could not read map ID from savegame.", ERR_FG)
            self._btn.configure(state="disabled", bg="#555")
            return
        zp = find_map_zip(mid)
        map_name = mid.split(".")[0]
        if not zp:
            self._set_status(f"Map ZIP not found for: {map_name}", ERR_FG)
            self._btn.configure(state="disabled", bg="#555")
            return

        # Check already patched
        try:
            with zipfile.ZipFile(zp, "r") as z:
                i3d = find_i3d_path(z)
                if i3d:
                    content = z.read(i3d).decode("utf-8-sig", errors="ignore")
                    if already_patched(content):
                        self._set_status(f"Already patched: {map_name}", ACCENT)
                        self._btn.configure(text="Already Patched  ✓", state="disabled", bg="#555")
                        return
        except Exception:
            pass

        self._set_status(f"Ready — {map_name}", ACCENT)

    def _on_run(self):
        self._btn.configure(state="disabled", bg="#555", text="Installing…")
        self._set_status("Running…", DIM_FG)
        self._log_append("Starting installer...\n")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            ok, result = run_installer(lambda msg: self.after(0, self._log_append, msg))
            self.after(0, self._on_done, ok, result)
        except Exception as e:
            self.after(0, self._on_error, str(e))

    def _on_done(self, ok, result):
        if result == "already_patched":
            self._btn.configure(text="Already Patched  ✓", bg="#555")
            self._set_status("Map was already patched.", ACCENT)
            messagebox.showinfo(
                "Nothing to do",
                "This map is already patched!\n\nYou can load your savegame right now.")
        elif ok:
            self._btn.configure(text="Done  ✓", bg="#555")
            self._set_status("Patch applied successfully!", ACCENT)
            messagebox.showinfo(
                "All done!",
                "5 soil layers successfully added to your map.\n\n"
                "Launch Farming Simulator 25 and load your save.\n"
                "The mod will detect the new layers automatically.")
        else:
            self._btn.configure(text="Partial — see log", bg="#c09000")
            self._set_status("Partial success — check log.", ERR_FG)
            messagebox.showwarning(
                "Partial success",
                "Some layers may not have been applied correctly.\n\n"
                "Check the log for details.\n"
                "Your original ZIP was backed up before any changes.")

    def _on_error(self, msg):
        self._btn.configure(state="normal", bg=ACCENT, text="Run Installer")
        self._set_status("Error — see below.", ERR_FG)
        self._log_append(f"\nERROR: {msg}")
        messagebox.showerror("Error", msg)

# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = InstallerApp()
    app.mainloop()
