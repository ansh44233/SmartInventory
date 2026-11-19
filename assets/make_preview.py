"""
Generate dashboard-preview.png using Pillow only.
Run: python assets/make_preview.py
"""
from PIL import Image, ImageDraw, ImageFont
import os

W, H = 1200, 720

# ── colours ─────────────────────────────────────────────────
BG       = (13,  17,  23)
SURFACE  = (22,  27,  34)
SURFACE2 = (13,  17,  23)
BORDER   = (48,  54,  61)
TEXT     = (230, 237, 243)
MUTED    = (125, 133, 144)
BLUE     = (88,  166, 255)
GREEN    = (63,  185, 80)
AMBER    = (210, 153, 34)
RED      = (248, 81,  73)
WHITE    = (255, 255, 255)

img  = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

# ── font helpers ─────────────────────────────────────────────
def font(size, bold=False):
    try:
        name = "arialbd.ttf" if bold else "arial.ttf"
        return ImageFont.truetype(name, size)
    except:
        return ImageFont.load_default()

FN    = font(12)
FN_B  = font(12, bold=True)
FN_S  = font(10)
FN_XS = font(9)
FN_L  = font(28, bold=True)
FN_M  = font(14, bold=True)
FN_T  = font(16, bold=True)

def text(x, y, s, f=FN, fill=TEXT, anchor="lt"):
    draw.text((x, y), s, font=f, fill=fill, anchor=anchor)

def rect(x, y, w, h, fill=SURFACE, radius=8, outline=BORDER, outline_w=1):
    draw.rounded_rectangle([x, y, x+w, y+h], radius=radius, fill=fill,
                           outline=outline, width=outline_w)

def line(x1, y1, x2, y2, fill=BORDER, w=1):
    draw.line([(x1, y1), (x2, y2)], fill=fill, width=w)

def pill(x, y, label, bg, fg, border):
    tw = draw.textlength(label, font=FN_S)
    pw = int(tw) + 18
    ph = 20
    draw.rounded_rectangle([x, y, x+pw, y+ph], radius=10,
                           fill=bg, outline=border, width=1)
    draw.text((x + pw//2, y + ph//2), label, font=FN_S, fill=fg, anchor="mm")
    return pw

# ── topbar ───────────────────────────────────────────────────
draw.rectangle([0, 0, W, 52], fill=SURFACE)
line(0, 52, W, 52)
text(20, 16, "📦  SmartInventory", f=FN_T, fill=TEXT)
draw.rounded_rectangle([196, 15, 232, 37], radius=11,
                       fill=(20, 40, 70), outline=(58, 90, 138), width=1)
text(214, 26, "v1.0", f=FN_XS, fill=BLUE, anchor="mm")
draw.ellipse([1162, 20, 1178, 36], fill=GREEN)
text(1155, 26, "Live", f=FN_XS, fill=MUTED, anchor="rm")

# ── section: Overview ────────────────────────────────────────
text(20, 68, "OVERVIEW", f=FN_XS, fill=MUTED)

kpis = [
    (20,   "TOTAL REVENUE", "₹1,22,000", BLUE),
    (306,  "PRODUCTS",      "20",         GREEN),
    (592,  "ORDERS",        "60",         AMBER),
    (878,  "LOW-STOCK ALERTS","4",        RED),
]
for kx, label, value, color in kpis:
    kw = 274 if kx < 870 else 302
    rect(kx, 82, kw, 86)
    draw.rounded_rectangle([kx, 82, kx+kw, 84], radius=0, fill=color)
    draw.rounded_rectangle([kx, 82, kx+kw, 86], radius=0,
                           fill=color, outline=color, width=0)
    # top accent bar
    draw.rounded_rectangle([kx, 82, kx+kw, 85], radius=4, fill=color)
    text(kx+16, 100, label, f=FN_XS, fill=MUTED)
    text(kx+16, 128, value, f=FN_L, fill=color)
    text(kx+16, 158, "non-cancelled orders" if kx==20 else
                     "across all categories" if kx==306 else
                     "total placed" if kx==592 else
                     "unresolved, DB trigger", f=FN_XS, fill=MUTED)

# ── section: Analytics ───────────────────────────────────────
text(20, 192, "ANALYTICS", f=FN_XS, fill=MUTED)

# ── Chart card 1: Monthly Revenue ────────────────────────────
rect(20, 202, 572, 220)
text(36, 220, "Monthly Revenue",    f=FN_M, fill=TEXT)
text(36, 238, "Trend over last 90 days", f=FN_XS, fill=MUTED)

# grid lines
chart_y_bottom = 400
chart_x_left   = 70
chart_x_right  = 560
for gy in [400, 365, 330, 295]:
    line(chart_x_left, gy, chart_x_right, gy, fill=(33, 38, 45))

# y-axis labels
for gy, lbl in [(400,"0"),(365,"10K"),(330,"20K"),(295,"30K")]:
    text(chart_x_left-6, gy, lbl, f=FN_XS, fill=MUTED, anchor="rm")

# data points (month, y)
pts = [(110,390),(215,363),(320,330),(425,305),(530,278)]
xlbls = [(110,"Aug"),(215,"Sep"),(320,"Oct"),(425,"Nov"),(530,"Nov+")]

# area fill (simple polygon)
poly = [(x, y) for x,y in pts] + [(pts[-1][0], chart_y_bottom), (pts[0][0], chart_y_bottom)]
draw.polygon(poly, fill=(88, 166, 255, 20))

# line
for i in range(len(pts)-1):
    draw.line([pts[i], pts[i+1]], fill=BLUE, width=2)

# dots
for px, py in pts:
    draw.ellipse([px-4, py-4, px+4, py+4], fill=BLUE)

# x labels
for px, lbl in xlbls[:-1]:
    text(px, chart_y_bottom+8, lbl, f=FN_XS, fill=MUTED, anchor="mt")

# ── Chart card 2: Top Products ────────────────────────────────
rect(608, 202, 572, 220)
text(624, 220, "Top Products by Revenue", f=FN_M, fill=TEXT)
text(624, 238, "Non-cancelled orders only", f=FN_XS, fill=MUTED)

bars = [
    ("Smart Watch Gen2",   420, "₹71,988"),
    ("Air Fryer 4L",       295, "₹23,994"),
    ("Mechanical Keyboard",235, "₹17,495"),
    ("Wireless Earbuds Pro",185,"₹14,994"),
    ("Bluetooth Speaker",  150, "₹12,593"),
]
bar_y = 262
for name, bw, rev in bars:
    text(624, bar_y, name, f=FN_S, fill=TEXT)
    bar_y += 16
    draw.rounded_rectangle([624, bar_y, 624+bw, bar_y+14],
                           radius=3, fill=GREEN)
    text(624+bw+8, bar_y+7, rev, f=FN_XS, fill=MUTED, anchor="lm")
    bar_y += 22

# ── Stock Alerts table ────────────────────────────────────────
text(20, 440, "STOCK ALERTS", f=FN_XS, fill=MUTED)
text(130, 440, "(trigger-generated)", f=FN_XS, fill=RED)
rect(20, 452, 1160, 148)

# header row
draw.rectangle([20, 452, 1180, 476], fill=SURFACE2)
for hx, hl in [(36,"SKU"),(150,"PRODUCT"),(460,"STOCK"),(560,"REORDER LEVEL"),
               (690,"ALERT"),(840,"TRIGGERED")]:
    text(hx, 462, hl, f=FN_XS, fill=MUTED)
line(20, 476, 1180, 476)

# alert rows
alerts = [
    ("SKU-0009","Air Fryer 4L",          "3","10","1h ago"),
    ("SKU-0015","Smart Watch Gen2",       "4","10","2h ago"),
    ("SKU-0019","Board Game Catan",       "5","10","1d ago"),
    ("SKU-0003","Mechanical Keyboard",    "7","10","2d ago"),
]
row_y = 486
for sku, name, stock, reorder, when in alerts:
    text(36,  row_y, sku,     f=font(11), fill=MUTED)
    text(150, row_y, name,    f=font(11, bold=True), fill=RED)
    pill(455, row_y-4, stock, (60,15,15), RED, (100,30,30))
    text(560, row_y, reorder, f=FN_S, fill=TEXT)
    pill(685, row_y-4, "low_stock", (55,40,10), AMBER, (90,70,15))
    text(840, row_y, when,    f=FN_S, fill=MUTED)
    row_y += 28
    if row_y < 596:
        line(20, row_y-6, 1180, row_y-6, fill=(33,38,45))

# ── footer ────────────────────────────────────────────────────
line(20, 616, 1180, 616)
text(20,   632, "SmartInventory · Python + PostgreSQL · FastAPI", f=FN_S, fill=MUTED)
text(1180, 632, "Refreshed 12:14:33 PM", f=FN_S, fill=MUTED, anchor="rt")

# ── save ──────────────────────────────────────────────────────
out = os.path.join(os.path.dirname(__file__), "dashboard-preview.png")
img.save(out, "PNG", optimize=True)
print(f"Saved: {out}  ({W}x{H})")
