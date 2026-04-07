# Deploy Konnekt to Railway — 10-Minuten-Anleitung

## Was du bekommst
- Echte HTTPS-URL (z.B. `https://konnekt-xyz.up.railway.app`)
- Kostenlos bis 500 Stunden/Monat (Hobby-Plan)
- Automatisches SSL-Zertifikat
- PWA-Install funktioniert auf jedem Handy

---

## Schritt 1: Impressum fertigstellen

In `api/app.py` folgende Zeile anpassen:
```
OWNER_EMAIL   = "hello@konnekt.app"   ← deine echte E-Mail eintragen!
```
Name und Adresse sind bereits ausgefüllt (Muharrem Akdemir, Schaalweg 6, Münchenbuchsee).

---

## Schritt 2: GitHub Repo erstellen

```bash
cd ~/konnekt
git init
git add -A
git commit -m "feat: Konnekt beta launch"
# Dann auf github.com neues Repo erstellen (z.B. "konnekt-beta")
git remote add origin https://github.com/DEIN-USERNAME/konnekt-beta.git
git push -u origin main
```

---

## Schritt 3: Railway deployen

1. Gehe zu [railway.app](https://railway.app) → "Start a New Project"
2. "Deploy from GitHub repo" → dein konnekt-beta Repo auswählen
3. Railway erkennt automatisch Python + Procfile

**Environment Variables** setzen (Railway Dashboard → Variables):
```
SECRET_KEY=7d9debdae7d680880c131b74a445c66040e9f4baf8073e3e16a5aeb36cfb26ce
PORT=8080
DATA_DIR=/data
STRIPE_PRO_PRICE_ID=price_1TJT6cJj5CtfTvT6loIfLjrn
STRIPE_BUSINESS_PRICE_ID=price_1TJT80Jj5CtfTvT66B8gKxnc
```
Add `STRIPE_SECRET_KEY=sk_live_...` (from Stripe Dashboard → Developers → API keys) once you go live.

4. Unter "Volumes" → "Add Volume" → Mount Path: `/data` (persistente DB!)
5. Deploy läuft automatisch durch

---

## Schritt 4: Deine URL bekommen

Railway gibt dir eine URL wie:
```
https://konnekt-production-abc.up.railway.app
```

Optional: Eigene Domain (z.B. `konnekt.app`) kostet ca. 10 CHF/Jahr bei Infomaniak.

---

## Schritt 5: QR-Code neu generieren mit echter URL

```bash
cd ~/konnekt
python3 make_qr.py https://konnekt-production-abc.up.railway.app/landing
```

Öffne `stickers/sticker_sheet_A4.html` in Chrome → Drucken → PDF → Aufkleber!

---

## Schritt 6: Datenbank mit Demo-Daten befüllen

```bash
# Lokal (einmalig):
cd ~/konnekt
python3 seed_rich.py

# Dann DB-Datei auf Railway hochladen (via Railway CLI):
npm install -g @railway/cli
railway login
railway run python3 seed_rich.py
```

---

## Wo sticker aufkleben?

**Bern:**
- Schwarztorstrasse / Länggasse (Uni-Bereich)
- Waisenhausplatz-Umgebung
- Hirschenpark / Lorraine-Quartier
- Schwarzes Brett: Caritas Bern, Heiliggeistkirche, Reitschule
- Schwarzes Brett Uni Bern (Hauptgebäude + Vonrollstrasse)
- Migros / Coop-Eingänge (Flyer auf Info-Board)
- Gemeindeverwaltungen

**Online (gratis):**
- Post in: r/bern, Facebook-Gruppe "Bern - Nachbarschaftshilfe"
- nextdoor.com (Nachbarschafts-App)
- Instagram Story mit Link-Sticker
- WhatsApp-Gruppen

---

## Passives Wachstum — was schon drin ist

✓ **Invite-Links**: Jeder User kann `/api/invite/generate` aufrufen → bekommt Link
✓ **Waitlist**: Wer sich einträgt → du siehst E-Mails, kannst nachfassen
✓ **Rangliste**: Öffentlich sichtbar → motiviert andere mitzumachen
✓ **Gute-Taten-Feed**: Andere sehen was passiert → FOMO-Effekt ohne Algorithmus
✓ **Punkte-System**: Intrinsischer Anreiz zurückzukommen

## 100 User in 30 Tagen — realistischer Plan

| Woche | Aktion | Erwartete User |
|-------|--------|----------------|
| 1 | Sticker Uni Bern + Lorraine | 10–20 |
| 2 | Post r/bern + Facebook Bern | 15–30 |
| 3 | 1 NGO kontaktieren (Caritas/Rotkreuz) | +20–40 |
| 4 | Word of mouth (Punkte-System zieht) | passiv +20 |

**Schlüssel:** 1 NGO als Partner = sofort 20–50 echte aktive User.
Ruf bei Caritas Bern an: +41 31 388 40 70 — zeig die App, frag ob sie Events eintragen wollen.
