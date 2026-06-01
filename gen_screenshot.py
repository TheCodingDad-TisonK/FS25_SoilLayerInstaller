"""Generate screenshot.png for FS25_SoilLayerInstaller README."""
from PIL import Image, ImageDraw, ImageFont
import os

# ── Palette ───────────────────────────────────────────────────────────────────
BG         = (18,  22,  28)
PANEL_BG   = (26,  32,  40)
BORDER     = (44,  52,  64)
TITLE_CLR  = (230, 235, 245)
SUB_CLR    = (140, 150, 165)
HEAD_CLR   = (210, 165,  60)   # amber
TEXT_CLR   = (185, 195, 210)
STATUS_OK  = (80,  200, 120)
STATUS_LBL = (120, 130, 145)
LOG_CLR    = (140, 200, 140)
LOG_KEY    = (100, 160, 220)
BTN_BG     = (45,  140,  75)
BTN_HOV    = (55,  160,  85)
BTN_TXT    = (240, 250, 240)
CONSOLE_BG = (12,  16,  22)

W, H = 560, 780

img  = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

# ── Fonts ─────────────────────────────────────────────────────────────────────
def font(size, bold=False):
    candidates = [
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    if bold:
        candidates = [
            "C:/Windows/Fonts/consolab.ttf",
            "C:/Windows/Fonts/courbd.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ] + candidates
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

F_TITLE  = font(20, bold=True)
F_SUB    = font(11)
F_HEAD   = font(12, bold=True)
F_BODY   = font(11)
F_LOG    = font(10)
F_BTN    = font(13, bold=True)
F_STATUS = font(11)

# ── Helpers ───────────────────────────────────────────────────────────────────
def rrect(draw, xy, radius=6, fill=PANEL_BG, outline=BORDER, width=1):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill, outline=outline, width=width)

def text(draw, pos, s, font, fill, anchor="la"):
    draw.text(pos, s, font=font, fill=fill, anchor=anchor)

# ── Title bar ─────────────────────────────────────────────────────────────────
PAD = 18
y = 18
text(draw, (PAD, y),      "FS25  Soil Layer Installer", F_TITLE, TITLE_CLR)
y += 26
text(draw, (PAD, y),      "Adds per-pixel nutrient tracking to your map mod.", F_SUB, SUB_CLR)
y += 22

# ── Info panels ───────────────────────────────────────────────────────────────
panels = [
    ("What it does", [
        "Patches your active map mod ZIP to add eight soil info layers",
        "(N, P, K, pH, Organic Matter, Pest, Disease, Compaction).",
        "FS25_SoilFertilizer uses these for real per-pixel heatmaps",
        "instead of field averages.",
    ]),
    ("What it checks", [
        "• Your active savegame folder",
        "• The map mod that savegame uses",
        "• Whether the patch has already been applied",
    ]),
    ("What it writes", [
        "• Your map mod ZIP  (a backup is created first)",
        "• Eight blank GRLE data files inside the ZIP",
        "• Nothing else — no registry, no settings files",
    ]),
    ("After running", [
        "Launch Farming Simulator 25 and load your save.",
        "The mod detects the new layers automatically.",
        "No extra steps needed.",
    ]),
]

for head, lines in panels:
    line_h = 15
    ph = 14 + 18 + len(lines) * line_h + 6
    rrect(draw, (PAD, y, W - PAD, y + ph))
    text(draw, (PAD + 10, y + 10), head, F_HEAD, HEAD_CLR)
    for i, ln in enumerate(lines):
        text(draw, (PAD + 10, y + 28 + i * line_h), ln, F_BODY, TEXT_CLR)
    y += ph + 8

y += 4

# ── Status bar ────────────────────────────────────────────────────────────────
rrect(draw, (PAD, y, W - PAD, y + 28), radius=5, fill=PANEL_BG, outline=BORDER)
text(draw, (PAD + 10, y + 8), "Status:", F_STATUS, STATUS_LBL)
text(draw, (PAD + 64, y + 8), "Ready — FS25_The_Pichonniere_Valley", F_STATUS, STATUS_OK)
y += 36

# ── Console log ───────────────────────────────────────────────────────────────
log_lines = [
    ("plain", "Scanning for active savegame..."),
    ("key",   "  Savegame : savegame1"),
    ("key",   "  Map ID   : FS25_The_Pichonniere_Valley.mapXX"),
    ("key",   "  Map ZIP  : FS25_The_Pichonniere_Valley.zip"),
    ("key",   "  i3d file : maps/mapXX.i3d"),
    ("key",   "  GRLE template: 4,096 bytes"),
    ("plain", "Adding layers (fileIds 1021-1028):"),
    ("ok",    "  + soilN        (id=1021)"),
    ("ok",    "  + soilP        (id=1022)"),
    ("ok",    "  + soilK        (id=1023)"),
    ("ok",    "  + soilPH       (id=1024)"),
    ("ok",    "  + soilOM       (id=1025)"),
    ("ok",    "  + soilPest     (id=1026)"),
    ("ok",    "  + soilDisease  (id=1027)"),
    ("ok",    "  + soilCompaction (id=1028)"),
]
log_h = 12
console_h = len(log_lines) * log_h + 16
rrect(draw, (PAD, y, W - PAD, y + console_h), radius=5, fill=CONSOLE_BG, outline=BORDER)
for i, (kind, ln) in enumerate(log_lines):
    clr = LOG_KEY if kind == "key" else (LOG_CLR if kind == "ok" else TEXT_CLR)
    text(draw, (PAD + 10, y + 8 + i * log_h), ln, F_LOG, clr)
y += console_h + 12

# ── Run button ────────────────────────────────────────────────────────────────
bw, bh = W - 2 * PAD, 44
rrect(draw, (PAD, y, PAD + bw, y + bh), radius=8, fill=BTN_BG, outline=BTN_HOV, width=2)
text(draw, (PAD + bw // 2, y + bh // 2), "Run Installer", F_BTN, BTN_TXT, anchor="mm")
y += bh + 10

# ── Crop to content ───────────────────────────────────────────────────────────
img = img.crop((0, 0, W, y))
img.save("screenshot.png")
print(f"screenshot.png written ({W}×{y})")
