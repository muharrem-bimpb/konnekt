#!/usr/bin/env python3
"""
seed_rich.py — Populate Konnekt with max demo data for Bern.
Run once: python3 seed_rich.py
Safe to re-run: checks for existing data first.
"""
import sqlite3, hashlib, secrets, json
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent / "data" / "konnekt.db"
SECRET  = "7d9debdae7d680880c131b74a445c66040e9f4baf8073e3e16a5aeb36cfb26ce"  # matches .env

def h(pw): return hashlib.sha256((pw + SECRET[:16]).encode()).hexdigest()

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")
c = conn.cursor()

# Init tables (same schema as api/app.py)
c.executescript("""
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, display_name TEXT, bio TEXT DEFAULT '', avatar_url TEXT DEFAULT '', city TEXT DEFAULT '', lat REAL DEFAULT 0, lng REAL DEFAULT 0, points_balance INTEGER DEFAULT 0, volunteer_hours INTEGER DEFAULT 0, is_senior INTEGER DEFAULT 0, needs_visitor INTEGER DEFAULT 0, is_verified INTEGER DEFAULT 0, is_ngo INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, organizer_id INTEGER NOT NULL, title TEXT NOT NULL, description TEXT DEFAULT '', category TEXT DEFAULT 'other', address TEXT DEFAULT '', city TEXT DEFAULT '', lat REAL DEFAULT 0, lng REAL DEFAULT 0, starts_at TEXT NOT NULL, ends_at TEXT, max_participants INTEGER DEFAULT 0, participants_count INTEGER DEFAULT 0, points_reward INTEGER DEFAULT 50, image_url TEXT DEFAULT '', status TEXT DEFAULT 'active', tags TEXT DEFAULT '[]', created_at TEXT DEFAULT (datetime('now')), FOREIGN KEY(organizer_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS event_registrations (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, user_id INTEGER NOT NULL, status TEXT DEFAULT 'registered', points_awarded INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')), UNIQUE(event_id, user_id), FOREIGN KEY(event_id) REFERENCES events(id), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS businesses (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, name TEXT NOT NULL, description TEXT DEFAULT '', category TEXT DEFAULT 'other', address TEXT DEFAULT '', city TEXT DEFAULT '', lat REAL DEFAULT 0, lng REAL DEFAULT 0, logo_url TEXT DEFAULT '', website TEXT DEFAULT '', verified INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS coupons (id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, title TEXT NOT NULL, description TEXT DEFAULT '', points_cost INTEGER NOT NULL, valid_until TEXT, max_redemptions INTEGER DEFAULT 0, redemptions_count INTEGER DEFAULT 0, category TEXT DEFAULT 'other', status TEXT DEFAULT 'active', created_at TEXT DEFAULT (datetime('now')), FOREIGN KEY(business_id) REFERENCES businesses(id));
CREATE TABLE IF NOT EXISTS coupon_redemptions (id INTEGER PRIMARY KEY AUTOINCREMENT, coupon_id INTEGER NOT NULL, user_id INTEGER NOT NULL, qr_code TEXT UNIQUE NOT NULL, redeemed_at TEXT DEFAULT (datetime('now')), confirmed_at TEXT, FOREIGN KEY(coupon_id) REFERENCES coupons(id), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS neighbor_connections (id INTEGER PRIMARY KEY AUTOINCREMENT, user_a INTEGER NOT NULL, user_b INTEGER NOT NULL, status TEXT DEFAULT 'pending', connection_type TEXT DEFAULT 'friend', created_at TEXT DEFAULT (datetime('now')), UNIQUE(user_a, user_b), FOREIGN KEY(user_a) REFERENCES users(id), FOREIGN KEY(user_b) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS senior_visits (id INTEGER PRIMARY KEY AUTOINCREMENT, senior_id INTEGER NOT NULL, visitor_id INTEGER NOT NULL, scheduled_at TEXT NOT NULL, duration_min INTEGER DEFAULT 60, completed INTEGER DEFAULT 0, points_awarded INTEGER DEFAULT 0, note TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')), FOREIGN KEY(senior_id) REFERENCES users(id), FOREIGN KEY(visitor_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS good_deeds (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL, points_earned INTEGER DEFAULT 25, verified INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS activity_suggestions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL, category TEXT DEFAULT 'social', description TEXT DEFAULT '', lat REAL DEFAULT 0, lng REAL DEFAULT 0, city TEXT DEFAULT '', accepted INTEGER DEFAULT 0, points_awarded INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS feed_items (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, ref_id INTEGER, user_id INTEGER, content TEXT DEFAULT '', city TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS point_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, delta INTEGER NOT NULL, reason TEXT NOT NULL, ref_type TEXT, ref_id INTEGER, created_at TEXT DEFAULT (datetime('now')), FOREIGN KEY(user_id) REFERENCES users(id));
""")
conn.commit()

# ── Skip if already seeded ──────────────────────────────────────────────────
user_count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
if user_count >= 10:
    print(f"Already {user_count} users — skipping. Delete data/konnekt.db to re-seed.")
    conn.close()
    exit(0)

print("Seeding Konnekt with rich Bern demo data...")

# ── Users ───────────────────────────────────────────────────────────────────
# avatar_url: pravatar gives deterministic faces per email hash
users = [
    # (username, email, display_name, bio, city, is_senior, needs_visitor, is_ngo, points)
    ("leila_bern",   "leila@demo.konnekt", "Leila Meseret",    "Sozialarbeiterin im Lorraine-Quartier", "Bern", 0,0,0, 340),
    ("max_freiwillig","max@demo.konnekt",  "Max Gerber",       "Freiwilliger seit 5 Jahren, Wankdorf",  "Bern", 0,0,0, 820),
    ("oma_rosa",     "rosa@demo.konnekt",  "Rosa Zimmermann",  "Rentnerin, mag Gesellschaft & Tee",     "Bern", 1,1,0, 120),
    ("ali_helper",   "ali@demo.konnekt",   "Ali Güven",        "Studiert Soziale Arbeit, Länggasse",    "Bern", 0,0,0, 560),
    ("nahbar_org",   "ngo@demo.konnekt",   "Nahbar Bern e.V.", "Offizieller NGO-Account",               "Bern", 0,0,1, 0),
    ("yara_aktiv",   "yara@demo.konnekt",  "Yara Schäfer",     "Umweltaktivistin, Breitenrain",         "Bern", 0,0,0, 290),
    ("opa_hans",     "hans@demo.konnekt",  "Hans Keller",      "90 Jahre jung, freue mich über Besuch", "Bern", 1,1,0,  80),
    ("sara_coach",   "sara@demo.konnekt",  "Sara Baumgartner", "Laufcoach & Yoga-Lehrerin, Bümpliz",    "Bern", 0,0,0, 450),
    ("kiri_ngo",     "kiri@demo.konnekt",  "Kiri Tanaka",      "Koordinatorin Caritas Bern",            "Bern", 0,0,1, 200),
    ("tom_nebenan",  "tom@demo.konnekt",   "Tom Wüthrich",     "Nachbar, mag guten Kaffee & Gespräche", "Bern", 0,0,0, 180),
    ("maya_matte",   "maya@demo.konnekt",  "Maya Etter",       "Mattenhof — Mutter & Freiwillige",      "Bern", 0,0,0, 640),
    ("erwin_senior", "erwin@demo.konnekt", "Erwin Stucki",     "Alt-Stadtrat, brauche Einkaufshilfe",   "Bern", 1,1,0,  50),
    ("finn_student", "finn@demo.konnekt",  "Finn Roth",        "Uni Bern Erstsemester, Kirchenfeld",    "Bern", 0,0,0, 110),
    ("amina_rotes_kreuz","amina@demo.konnekt","Amina Koller",  "Rotkreuz-Pflegerin & Freiwillige",      "Bern", 0,0,0, 780),
    ("demo",         "demo@konnekt.app",   "Demo Nutzer",      "Testaccount — probiere alles aus!",     "Bern", 0,0,0, 350),
]

uid_map = {}
for u in users:
    username, email, display_name, bio, city, is_senior, needs_visitor, is_ngo, pts = u
    avatar = f"https://i.pravatar.cc/150?u={email}"
    try:
        c.execute("""INSERT INTO users
            (username,email,password_hash,display_name,bio,avatar_url,city,
             lat,lng,points_balance,is_senior,needs_visitor,is_ngo,is_verified)
            VALUES (?,?,?,?,?,?,?,46.948,7.447,?,?,?,?,1)""",
            (username,email,h("demo123"),display_name,bio,avatar,city,
             pts,is_senior,needs_visitor,is_ngo))
        uid_map[username] = c.lastrowid
        print(f"  + user {display_name}")
    except sqlite3.IntegrityError:
        row = c.execute("SELECT id FROM users WHERE username=? OR email=?", (username, email)).fetchone()
        if row:
            uid_map[username] = row[0]

# ── Businesses (expanded) ────────────────────────────────────────────────────
c.execute("DELETE FROM businesses WHERE 1=1")
c.execute("DELETE FROM coupons WHERE 1=1")

businesses = [
    # (name, desc, category, address, city, lat, lng, logo_url)
    ("Bäckerei Gilgen",       "Traditionsreich seit 1892, Altstadt",           "food",    "Spitalgasse 4",       "Bern", 46.9480, 7.4472, "https://picsum.photos/seed/bakery_bern/80/80"),
    ("Sport & More Bern",     "Fitness, Yoga, Schwimmen im Wankdorf",          "sport",   "Wankdorfstrasse 11",  "Bern", 46.9637, 7.4668, "https://picsum.photos/seed/sport_bern/80/80"),
    ("Kulturhalle Reitschule","Konzerte, Kino, Bar — Kult seit 1987",          "culture", "Neubrückstrasse 8",   "Bern", 46.9488, 7.4373, "https://picsum.photos/seed/kultur_reitschule/80/80"),
    ("Frische Ecke Bio",      "100% regional & bio, Wochenmarkt",              "food",    "Bundesplatz 3",       "Bern", 46.9466, 7.4440, "https://picsum.photos/seed/biomarkt_bern/80/80"),
    ("Kino Rex",              "Unabhängiges Programmkino seit 1948",           "culture", "Schwanengasse 9",     "Bern", 46.9490, 7.4430, "https://picsum.photos/seed/kino_rex/80/80"),
    ("Café Kairo",            "Fairtrade-Kaffee & Veganes Essen, Lorraine",    "food",    "Dammweg 43",          "Bern", 46.9581, 7.4529, "https://picsum.photos/seed/cafe_lorraine/80/80"),
    ("Buchhandlung Stauffacher","Berns grösste unabhängige Buchhandlung",       "culture", "Neuengasse 25",       "Bern", 46.9469, 7.4449, "https://picsum.photos/seed/buch_bern/80/80"),
    ("Wasserwerk Club",       "Kulturzentrum & Konzerte unter der Kornhausbrücke","culture","Wasserwerkgasse 5",  "Bern", 46.9537, 7.4472, "https://picsum.photos/seed/wasserwerk/80/80"),
    ("Stadtgärtnerei Elfenau","Stadtpark, Führungen & Saisonpflanzen",         "sport",   "Elfenauweg 10",       "Bern", 46.9312, 7.4706, "https://picsum.photos/seed/garten_bern/80/80"),
    ("Aarbergergasse Markt",  "Wochenmarkt Di/Sa, lokale Produzenten",         "food",    "Aarbergergasse",      "Bern", 46.9452, 7.4427, "https://picsum.photos/seed/markt_aarb/80/80"),
]

biz_ids = []
for b in businesses:
    c.execute("""INSERT INTO businesses (name,description,category,address,city,lat,lng,logo_url,verified)
                 VALUES (?,?,?,?,?,?,?,?,1)""", b)
    biz_ids.append(c.lastrowid)

# ── Coupons (3–4 per business) ───────────────────────────────────────────────
valid = (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")
all_coupons = [
    (biz_ids[0], "Gratis Gipfeli",           "Jeden Morgen bis 9 Uhr — zeige App",     50,  "food"),
    (biz_ids[0], "10% Rabatt Backwaren",      "Code an der Kasse vorzeigen",           100,  "food"),
    (biz_ids[0], "Kaffee & Gipfeli Kombi",    "Für alle Freiwilligen",                  80,  "food"),
    (biz_ids[1], "Tagespass Fitness",         "1 Tag freier Eintritt",                 200,  "sport"),
    (biz_ids[1], "1 Monat Mitgliedschaft 50%","Für Neukunden",                         500,  "sport"),
    (biz_ids[1], "Yoga-Schnupperstunde",      "Nächster Samstag, 10 Uhr",              150,  "sport"),
    (biz_ids[2], "Konzert-Ticket -50%",       "Ausgewählte Veranstaltungen",           200,  "culture"),
    (biz_ids[2], "2-für-1 Bar-Eintritt",      "Do–Sa ab 21 Uhr",                       120,  "culture"),
    (biz_ids[3], "Gemüsebox der Woche",       "Saisonales Sortiment, abholbereit Fr",  120,  "food"),
    (biz_ids[3], "Fruchtsaft 1L gratis",      "Bei Einkauf ab 20 CHF",                  80,  "food"),
    (biz_ids[4], "2 Kinokarten zum Preis 1",  "Alle Vorstellungen gültig",             300,  "culture"),
    (biz_ids[4], "Popcorn gratis",            "Zum regulären Ticket",                  100,  "culture"),
    (biz_ids[5], "Kaffee gratis",             "1 Tasse Filterkaffee nach Wahl",         60,  "food"),
    (biz_ids[5], "Mittagsteller -20%",        "Mo–Fr 11:30–14:00 Uhr",                 150,  "food"),
    (biz_ids[6], "Buchgutschein 10 CHF",      "Für alle Bücher ausser Sale",           200,  "culture"),
    (biz_ids[7], "Konzert-Freiticket",        "Ausgewählte Abende, Kasse ab 19 Uhr",   350,  "culture"),
    (biz_ids[8], "Führung Elfenau",           "Sa 14 Uhr, Gruppe bis 10 Pers.",        100,  "sport"),
    (biz_ids[9], "Marktkorb 5 CHF Rabatt",    "Di/Sa Markt, min. 25 CHF Einkauf",       80,  "food"),
]
for cpn in all_coupons:
    c.execute("""INSERT INTO coupons (business_id,title,description,points_cost,category,valid_until,max_redemptions)
                 VALUES (?,?,?,?,?,?,100)""", (*cpn, valid))

# ── Events (20 events across Bern quarters) ──────────────────────────────────
# Images: picsum.photos/seed/<name>/600/400 — consistent, real photos
ngo_id  = uid_map.get("nahbar_org",  1)
leila   = uid_map.get("leila_bern",  1)
kiri    = uid_map.get("kiri_ngo",    1)
amina   = uid_map.get("amina_rotes_kreuz", 1)
yara    = uid_map.get("yara_aktiv",  1)

def dt(days_from_now, hour=10):
    return (datetime.now() + timedelta(days=days_from_now)).strftime(f"%Y-%m-%dT{hour:02d}:00:00")

events = [
    # (organizer, title, desc, category, address, city, lat, lng, starts_at, ends_at, max_p, pts, image_url, tags)
    (ngo_id, "Stadtputz Lorraine", "Gemeinsam das Lorraine-Quartier sauber halten! Handschuhe & Säcke werden gestellt.", "environment", "Lorrainebrücke, Bern", "Bern", 46.9581,7.4429, dt(2,9), dt(2,12),  30, 80,  "https://picsum.photos/seed/cleanup_lorraine/600/400",  '["umwelt","quartier"]'),
    (leila,  "Mittagstisch für Senioren", "Wöchentlicher Mittagstisch im Kirchgemeindehaus, Gäste 60+ willkommen.", "social",   "Waisenhausplatz 12, Bern","Bern",46.9496,7.4470, dt(3,11),dt(3,14), 20,100, "https://picsum.photos/seed/seniorentisch_bern/600/400", '["senioren","essen"]'),
    (kiri,   "Vorlesestunde Stadtbibliothek","Kinder-Vorlesestunde — Freiwillige als Vorleser gesucht!", "children",  "Münstergasse 61, Bern", "Bern", 46.9462,7.4516, dt(4,15),dt(4,17),  10, 60,  "https://picsum.photos/seed/bibliothek_bern/600/400",    '["kinder","bildung"]'),
    (yara,   "Aare aufräumen", "Müllsammlung entlang der Aare von Marzili bis Matte. Mit Picknick danach!", "environment","Marzilibad, Bern",      "Bern", 46.9420,7.4506, dt(5,9), dt(5,13), 40, 90,  "https://picsum.photos/seed/aare_aufraumen/600/400",     '["umwelt","aare"]'),
    (ngo_id, "Sprachkurs Deutsch-Café","Offenes Deutsch-Gespräch für Neuzugezogene — alle Niveaus.",    "education", "Café Kairo, Dammweg 43","Bern",  46.9581,7.4529, dt(6,17),dt(6,19),  15, 70,  "https://picsum.photos/seed/sprachcafe_bern/600/400",    '["sprache","integration"]'),
    (amina,  "Blutspende Aktion Bern","Rotes Kreuz Blutspende — 30 Min, Snack & Getränke danach.",         "health",    "Murtenstrasse 133, Bern","Bern",46.9380,7.4275, dt(7,8), dt(7,14), 60,120, "https://picsum.photos/seed/blutspende_bern/600/400",    '["gesundheit","roteskreuz"]'),
    (leila,  "Gartenarbeit Elfenau","Hilf im Stadtgarten der Elfenau — Pflanzen, Jäten, Ernte.",            "environment","Elfenauweg 10, Bern",   "Bern", 46.9312,7.4706, dt(8,10),dt(8,13), 12, 80,  "https://picsum.photos/seed/elfenau_garten/600/400",     '["garten","natur"]'),
    (ngo_id, "Nachbarschaftsfest Bümpliz","Quartierfest mit Grill, Musik und Spielen für Gross & Klein.", "social",    "Zentrum Bümpliz, Bern", "Bern", 46.9481,7.3881, dt(9,14),dt(9,20), 100,50,  "https://picsum.photos/seed/quartier_bumpliz/600/400",   '["fest","bümpliz"]'),
    (kiri,   "Repair Café Mattenhof","Kaputter Gegenstand? Wir reparieren gemeinsam — Fachleute helfen!", "environment","Mattenhofstrasse 5",    "Bern", 46.9370,7.4278, dt(10,14),dt(10,18),20,70,  "https://picsum.photos/seed/repair_cafe_bern/600/400",   '["nachhaltigkeit","reparieren"]'),
    (yara,   "Fahrrad-Tour Bern City","Geführte Radtour durch Berns schönste Quartiere, 2 Std.",            "sport",     "Bundesplatz, Bern",     "Bern", 46.9466,7.4440, dt(11,10),dt(11,12),25,60,  "https://picsum.photos/seed/velo_bern_tour/600/400",     '["velo","stadtführung"]'),
    (amina,  "Erste-Hilfe Kurs","Kostenloser Grundkurs für Freiwillige — Rotkreuz-Zertifikat.",             "health",    "Elfenstrasse 19, Bern", "Bern", 46.9440,7.4540, dt(14,9), dt(14,17),20,150, "https://picsum.photos/seed/erstehilfe_bern/600/400",    '["gesundheit","kurs"]'),
    (ngo_id, "Weihnachtsmarkt helfen","Aufbau & Abbau Weihnachtsmarkt Waisenhausplatz — fleissige Hände gesucht!","seasonal","Waisenhausplatz, Bern","Bern",46.9496,7.4470,dt(15,8),dt(15,12),15,90,  "https://picsum.photos/seed/weihnachtsmarkt_bern/600/400",'["weihnachten","markt"]'),
    (leila,  "Kleidertausch Breitenrain","Bring 5 Stück, nimm 5 Stück — gratis und nachhaltig.",           "environment","Breitenrainplatz 6",    "Bern", 46.9577,7.4551, dt(16,10),dt(16,14),50,40,  "https://picsum.photos/seed/kleidertausch_bern/600/400", '["nachhaltig","mode"]'),
    (kiri,   "Suppenküche Heiliggeist","Freiwillige Helfer für die Suppenküche am Bahnhof gesucht.",         "social",    "Heiliggeistkirche, Bern","Bern",46.9490,7.4397, dt(1,11),dt(1,14), 10,100, "https://picsum.photos/seed/suppenkueche_bern/600/400",  '["senioren","sozialhilfe"]'),
    (yara,   "Stadtbäume pflanzen","Mach mit beim Stadtbegrünungsprojekt der Stadt Bern.",                  "environment","Wankdorffeld, Bern",    "Bern", 46.9640,7.4668, dt(18,9),dt(18,13),20,100, "https://picsum.photos/seed/baum_pflanzen_bern/600/400", '["baum","klima"]'),
    (ngo_id, "Seniorenausflug Gurten","Begleitpersonen für Ausflug auf den Gurten gesucht!",                "social",    "Gurtenbahn, Wabern",    "Bern", 46.9210,7.4418, dt(20,10),dt(20,16),15,120, "https://picsum.photos/seed/gurten_ausflug/600/400",     '["senioren","ausflug"]'),
    (amina,  "Schwimmen für Senioren","Begleitung älterer Menschen im Schwimmbad — Di & Do.",               "sport",     "Hallenbad Hirschenpark","Bern", 46.9500,7.4380, dt(22,10),dt(22,12),8, 80,  "https://picsum.photos/seed/schwimmen_bern/600/400",     '["senioren","sport"]'),
    (leila,  "Lebensmittelbank sortieren","Foodbank Bern — Lebensmittel sortieren & verpacken.",             "social",    "Weissenbühlweg 24",     "Bern", 46.9348,7.4415, dt(23,9),dt(23,13), 12,90,  "https://picsum.photos/seed/foodbank_bern/600/400",      '["lebensmittel","sozialhilfe"]'),
    (kiri,   "Nachbarschaftshilfe App-Einführung","Zeig Senioren wie Konnekt funktioniert — 1:1 Einführung.", "education","Kornhaus, Bern",        "Bern", 46.9484,7.4470, dt(25,14),dt(25,16),8, 60,  "https://picsum.photos/seed/app_einf_bern/600/400",     '["digital","senioren"]'),
    (yara,   "Gemeinschaftsgarten Lorraine","Mitgärtnern im Gemeinschaftsgarten — offen für alle.",          "environment","Lorrainestrasse 30",    "Bern", 46.9600,7.4520, dt(26,10),dt(26,13),20,70,  "https://picsum.photos/seed/gemgarten_lorraine/600/400", '["garten","lorraine"]'),
]

for ev in events:
    org,title,desc,cat,addr,city,lat,lng,s,e,mx,pts,img,tags = ev
    c.execute("""INSERT INTO events
        (organizer_id,title,description,category,address,city,lat,lng,
         starts_at,ends_at,max_participants,points_reward,image_url,status,tags)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'active',?)""",
        (org,title,desc,cat,addr,city,lat,lng,s,e,mx,pts,img,tags))
    eid = c.lastrowid
    # Add to feed
    c.execute("INSERT INTO feed_items (type,ref_id,user_id,content,city) VALUES ('event',?,?,?,?)",
              (eid, org, title, city))

print(f"  + {len(events)} events")

# ── Good Deeds Feed ──────────────────────────────────────────────────────────
deeds = [
    (uid_map["leila_bern"],   "neighbor", "Hab meiner Nachbarin beim Tragen der Einkäufe geholfen. Sie war so dankbar! 🛒"),
    (uid_map["max_freiwillig"],"environment","Heute 2 kg Müll an der Aare aufgesammelt, bevor der Regen kam. 🌿"),
    (uid_map["ali_helper"],   "social",   "Einen verwirrten älteren Herrn am Bahnhof Bern nach Hause begleitet."),
    (uid_map["yara_aktiv"],   "environment","Beim Stadtputz Lorraine dabei — tolles Team, sauberer Platz! 💪"),
    (uid_map["sara_coach"],   "social",   "Kostenlose Laufeinheit für die Nachbarschaft organisiert. 10 Leute kamen!"),
    (uid_map["tom_nebenan"],  "neighbor", "Für Erwin (88) eingekauft und dabei gemütlich Kaffee getrunken. ☕"),
    (uid_map["maya_matte"],   "children", "Hausaufgabenhilfe für 3 Kinder im Mattenhof — 2 Stunden gut verbracht."),
    (uid_map["amina_rotes_kreuz"],"health","Blutgespendet und gleich 3 Freunde mitgebracht. 4 Beutel für Leben! ❤️"),
    (uid_map["finn_student"], "social",   "Sitze jeden Mittwoch mit Oma Rosa und lese ihr vor. Macht uns beiden Freude."),
    (uid_map["leila_bern"],   "environment","Baumpflanzaktion Wankdorf — 5 neue Bäume im Quartier! 🌳"),
    (uid_map["max_freiwillig"],"social",  "Suppenküche am Heiliggeist — 80 Portionen ausgeteilt. Voller Herz."),
    (uid_map["kiri_ngo"],     "social",   "Kleidertausch organisiert: 200 Stück zirkuliert, kein Stück Abfall."),
    (uid_map["yara_aktiv"],   "neighbor", "Meinem Nachbar beim Umzug geholfen. Jetzt kennen wir uns endlich! 😊"),
    (uid_map["demo"],         "social",   "Zum ersten Mal dabei beim Mittagstisch — werde nächste Woche wiederkommen!"),
]

for uid, cat, desc in deeds:
    c.execute("""INSERT INTO good_deeds (user_id,category,description,points_earned,verified)
                 VALUES (?,?,?,25,1)""", (uid, cat, desc))
    deed_id = c.lastrowid
    c.execute("INSERT INTO feed_items (type,ref_id,user_id,content,city) VALUES ('deed',?,?,?,'Bern')",
              (deed_id, uid, desc[:60]))
    # Award points
    c.execute("UPDATE users SET points_balance = points_balance + 25 WHERE id=?", (uid,))

print(f"  + {len(deeds)} good deeds")

# ── Senior visits ────────────────────────────────────────────────────────────
seniors   = [uid_map["oma_rosa"], uid_map["opa_hans"], uid_map["erwin_senior"]]
visitors  = [uid_map["finn_student"], uid_map["tom_nebenan"], uid_map["ali_helper"], uid_map["maya_matte"]]
import random
random.seed(42)

for i, s in enumerate(seniors):
    for j in range(3):
        vis = visitors[(i + j) % len(visitors)]
        days_ago = -(i * 7 + j * 3)
        scheduled = (datetime.now() + timedelta(days=days_ago)).strftime("%Y-%m-%dT14:00:00")
        done = 1 if days_ago < 0 else 0
        pts  = 100 if done else 0
        c.execute("""INSERT INTO senior_visits
            (senior_id,visitor_id,scheduled_at,duration_min,completed,points_awarded,note)
            VALUES (?,?,?,60,?,?,'Gemütliche Runde bei Tee und Keksen 🍪')""",
            (s, vis, scheduled, done, pts))
        if done:
            c.execute("UPDATE users SET points_balance = points_balance + 100, volunteer_hours = volunteer_hours + 1 WHERE id=?", (vis,))

print(f"  + {len(seniors)*3} senior visits")

# ── Neighbor connections ─────────────────────────────────────────────────────
pairs = [
    ("leila_bern",   "tom_nebenan"),
    ("max_freiwillig","sara_coach"),
    ("ali_helper",   "maya_matte"),
    ("finn_student", "oma_rosa"),   # cross-gen connection
    ("tom_nebenan",  "erwin_senior"),
    ("yara_aktiv",   "kiri_ngo"),
    ("amina_rotes_kreuz","leila_bern"),
]
for a, b in pairs:
    ua, ub = uid_map.get(a), uid_map.get(b)
    if ua and ub:
        try:
            c.execute("""INSERT INTO neighbor_connections (user_a,user_b,status,connection_type)
                         VALUES (?,?,'connected','friend')""", (ua, ub))
        except sqlite3.IntegrityError:
            pass

print(f"  + {len(pairs)} neighbor connections")

# ── Point transactions log ────────────────────────────────────────────────────
txns = [
    (uid_map["max_freiwillig"], 50,  "Willkommen bei Konnekt!",       "welcome", None),
    (uid_map["max_freiwillig"], 80,  "Stadtputz Lorraine abgeschlossen","event",  None),
    (uid_map["max_freiwillig"], 100, "Mittagstisch Senioren — danke!","event",   None),
    (uid_map["leila_bern"],     50,  "Willkommen",                    "welcome", None),
    (uid_map["leila_bern"],     90,  "Aare aufräumen",                "event",   None),
    (uid_map["amina_rotes_kreuz"],120,"Blutspende-Aktion Bern",       "event",   None),
    (uid_map["demo"],           50,  "Willkommen bei Konnekt!",       "welcome", None),
    (uid_map["demo"],           25,  "Gute Tat: Erster Eintrag",      "deed",    None),
]
for uid, delta, reason, rtype, rid in txns:
    c.execute("""INSERT INTO point_transactions (user_id,delta,reason,ref_type)
                 VALUES (?,?,?,?)""", (uid, delta, reason, rtype))

print(f"  + {len(txns)} point transactions")

# ── Sessions for demo user (auto-login) ──────────────────────────────────────
demo_uid   = uid_map.get("demo")
demo_token = "demo-token-konnekt-2026"
exp = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S")
try:
    c.execute("INSERT INTO sessions (token,user_id,expires_at) VALUES (?,?,?)",
              (demo_token, demo_uid, exp))
    print(f"  + demo token: {demo_token}")
except sqlite3.IntegrityError:
    pass

conn.commit()
conn.close()

print("\nDone! Konnekt seeded with:")
print(f"  {len(users)} users  |  {len(businesses)} businesses  |  {len(all_coupons)} coupons")
print(f"  {len(events)} events  |  {len(deeds)} good deeds")
print(f"\nDemo login: demo@konnekt.app / demo123")
print(f"Demo token (direct API): Authorization: Bearer {demo_token}")
