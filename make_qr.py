#!/usr/bin/env python3
"""
make_qr.py — Generate print-ready QR sticker for Konnekt.
Run AFTER deploying: python3 make_qr.py https://your-app.railway.app
"""
import sys, os

URL = sys.argv[1] if len(sys.argv) > 1 else "https://konnekt.up.railway.app/landing"

try:
    import qrcode
    from qrcode.image.pure import PyPNGImage
except ImportError:
    print("Run: pip install qrcode[pil]")
    sys.exit(1)

out_dir = os.path.join(os.path.dirname(__file__), "stickers")
os.makedirs(out_dir, exist_ok=True)

# ── QR PNG ────────────────────────────────────────────────────────────────────
qr = qrcode.QRCode(
    version=None,
    error_correction=qrcode.constants.ERROR_CORRECT_H,  # 30% damage-proof
    box_size=12,
    border=2,
)
qr.add_data(URL)
qr.make(fit=True)
img = qr.make_image(fill_color="#0a0f1e", back_color="white")
qr_path = os.path.join(out_dir, "konnekt_qr.png")
img.save(qr_path)
print(f"✓ QR PNG: {qr_path}")

# ── Printable HTML sticker sheet (A4, 6 stickers) ────────────────────────────
html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Konnekt QR Stickers</title>
<style>
  @page {{ size: A4; margin: 15mm; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; background: white; }}
  .sheet {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8mm;
    width: 180mm;
    margin: 0 auto;
  }}
  .sticker {{
    border: 2px solid #0a0f1e;
    border-radius: 6mm;
    padding: 5mm;
    text-align: center;
    page-break-inside: avoid;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2mm;
  }}
  .sticker-logo {{ font-size: 13pt; font-weight: 900; letter-spacing: -.02em; color: #0a0f1e; }}
  .sticker-logo span {{ color: #3b82f6; }}
  .sticker-qr {{ width: 55mm; height: 55mm; }}
  .sticker-cta {{
    font-size: 8.5pt; font-weight: 700; color: #0a0f1e;
    background: #f0f9ff; border-radius: 3mm; padding: 2mm 4mm;
    border: 1px solid #bae6fd;
  }}
  .sticker-sub {{ font-size: 6.5pt; color: #64748b; line-height: 1.4; }}
  .sticker-url {{ font-size: 5.5pt; color: #94a3b8; font-family: monospace; margin-top: 1mm; }}
  .sticker-badges {{
    display: flex; gap: 2mm; flex-wrap: wrap; justify-content: center;
  }}
  .badge {{
    font-size: 6pt; padding: .8mm 2mm; border-radius: 99mm;
    border: 1px solid #e2e8f0; color: #64748b;
  }}
  .page-title {{
    text-align: center; font-size: 9pt; color: #94a3b8;
    margin-bottom: 6mm;
  }}
  @media print {{
    .page-title {{ display: none; }}
  }}
</style>
</head>
<body>
<p class="page-title">Konnekt Beta Stickers — ausschneiden & aufkleben · URL: {URL}</p>
<div class="sheet">
{''.join([f"""
  <div class="sticker">
    <div class="sticker-logo">🌐 <span>Konnekt</span></div>
    <img class="sticker-qr" src="konnekt_qr.png" alt="QR Code">
    <div class="sticker-cta">📲 Einfach scannen & installieren</div>
    <div class="sticker-sub">Ehrenamt · Nachbarschaft · Coupons<br>Verdiene Punkte für gute Taten</div>
    <div class="sticker-badges">
      <span class="badge">🌱 Beta</span>
      <span class="badge">🔒 Kostenlos</span>
      <span class="badge">📵 Kein Algorithmus</span>
    </div>
    <div class="sticker-url">{URL}</div>
  </div>
""" for _ in range(6)])}
</div>
</body>
</html>"""

html_path = os.path.join(out_dir, "sticker_sheet_A4.html")
with open(html_path, "w") as f:
    f.write(html)

print(f"✓ Sticker sheet: {html_path}")
print(f"\nOpen in Chrome → Print → 'Als PDF speichern' → auf Aufkleberpapier drucken")
print(f"Or send to any print shop as PDF.\n")
print(f"QR points to: {URL}")
