#!/usr/bin/env python3
"""
Konnekt — Social Impact Platform API
Two pillars: VolunteerHub + Nahbar (anti-loneliness)
Production-ready Flask REST API
"""
import os, json, sqlite3, hashlib, secrets, time, random
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path
from functools import wraps
from urllib.parse import urlencode

from dotenv import load_dotenv
from flask import Flask, g, request, jsonify, send_from_directory, render_template_string, redirect
from flask_cors import CORS
import requests as req

load_dotenv()

app = Flask(__name__, static_folder="../frontend/public", static_url_path="")
CORS(app, origins="*")

HOST   = os.getenv("HOST", "0.0.0.0")
PORT   = int(os.getenv("PORT", 8529))
DB     = os.getenv("DB_PATH", "../data/konnekt.db")
SECRET = os.getenv("SECRET_KEY", secrets.token_hex(32))

# ── OAuth / SSO ───────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_AUTH_URL      = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL     = "https://oauth2.googleapis.com/token"
GOOGLE_INFO_URL      = "https://www.googleapis.com/oauth2/v3/userinfo"

# In-memory stores (survive restarts only — fine for single-instance)
_magic_links: dict = {}                          # token → {email, expires}
_login_attempts: dict = defaultdict(list)        # ip → [timestamps]  (rate limiter)

# ── Stripe ────────────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY        = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRO_PRICE_ID      = os.getenv("STRIPE_PRO_PRICE_ID", "")
STRIPE_BUSINESS_PRICE_ID = os.getenv("STRIPE_BUSINESS_PRICE_ID", "")

# ── DB ────────────────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    # Support Railway volume mount at /data or local ../data
    data_dir = Path(os.getenv("DATA_DIR", "")) or Path(__file__).parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "konnekt.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            bio TEXT DEFAULT '',
            avatar_url TEXT DEFAULT '',
            city TEXT DEFAULT '',
            lat REAL DEFAULT 0,
            lng REAL DEFAULT 0,
            points_balance INTEGER DEFAULT 0,
            volunteer_hours INTEGER DEFAULT 0,
            is_senior INTEGER DEFAULT 0,
            needs_visitor INTEGER DEFAULT 0,
            is_verified INTEGER DEFAULT 0,
            is_ngo INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organizer_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT 'other',
            address TEXT DEFAULT '',
            city TEXT DEFAULT '',
            lat REAL DEFAULT 0,
            lng REAL DEFAULT 0,
            starts_at TEXT NOT NULL,
            ends_at TEXT,
            max_participants INTEGER DEFAULT 0,
            participants_count INTEGER DEFAULT 0,
            points_reward INTEGER DEFAULT 50,
            image_url TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            tags TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(organizer_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS event_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT DEFAULT 'registered',
            points_awarded INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(event_id, user_id),
            FOREIGN KEY(event_id) REFERENCES events(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT 'other',
            address TEXT DEFAULT '',
            city TEXT DEFAULT '',
            lat REAL DEFAULT 0,
            lng REAL DEFAULT 0,
            logo_url TEXT DEFAULT '',
            website TEXT DEFAULT '',
            verified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            points_cost INTEGER NOT NULL,
            valid_until TEXT,
            max_redemptions INTEGER DEFAULT 0,
            redemptions_count INTEGER DEFAULT 0,
            category TEXT DEFAULT 'other',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(business_id) REFERENCES businesses(id)
        );
        CREATE TABLE IF NOT EXISTS coupon_redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coupon_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            qr_code TEXT UNIQUE NOT NULL,
            redeemed_at TEXT DEFAULT (datetime('now')),
            confirmed_at TEXT,
            FOREIGN KEY(coupon_id) REFERENCES coupons(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS neighbor_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_a INTEGER NOT NULL,
            user_b INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            connection_type TEXT DEFAULT 'friend',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_a, user_b),
            FOREIGN KEY(user_a) REFERENCES users(id),
            FOREIGN KEY(user_b) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS senior_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            senior_id INTEGER NOT NULL,
            visitor_id INTEGER NOT NULL,
            scheduled_at TEXT NOT NULL,
            duration_min INTEGER DEFAULT 60,
            completed INTEGER DEFAULT 0,
            points_awarded INTEGER DEFAULT 0,
            note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(senior_id) REFERENCES users(id),
            FOREIGN KEY(visitor_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS good_deeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            points_earned INTEGER DEFAULT 25,
            verified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS activity_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            category TEXT DEFAULT 'social',
            description TEXT DEFAULT '',
            lat REAL DEFAULT 0,
            lng REAL DEFAULT 0,
            city TEXT DEFAULT '',
            accepted INTEGER DEFAULT 0,
            points_awarded INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS event_join_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            queue_position INTEGER DEFAULT 0,
            message TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(event_id, user_id),
            FOREIGN KEY(event_id) REFERENCES events(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS feed_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            ref_id INTEGER,
            user_id INTEGER,
            content TEXT DEFAULT '',
            city TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS point_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            reason TEXT NOT NULL,
            ref_type TEXT,
            ref_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            tier TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free','pro','business','ngo')),
            started_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT,
            stripe_customer_id TEXT DEFAULT '',
            stripe_subscription_id TEXT DEFAULT '',
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS legal_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_name TEXT NOT NULL,
            requester_org TEXT DEFAULT '',
            requester_email TEXT NOT NULL,
            purpose TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            status TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS life_bubbles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            emoji TEXT DEFAULT '✨',
            description TEXT DEFAULT '',
            lat REAL DEFAULT 0,
            lng REAL DEFAULT 0,
            address TEXT DEFAULT '',
            city TEXT DEFAULT '',
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """)
        # Add subscription_tier column to users if not exists (migration)
        try:
            c.execute("ALTER TABLE users ADD COLUMN subscription_tier TEXT DEFAULT 'free'")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Add type + is_public columns to events (migration)
        for col, defn in [("type", "TEXT DEFAULT 'volunteer'"), ("is_public", "INTEGER DEFAULT 1")]:
            try:
                c.execute(f"ALTER TABLE events ADD COLUMN {col} {defn}")
            except sqlite3.OperationalError:
                pass
        # Always ensure demo token/user exists first (other seeds depend on having a user)
        _ensure_demo_token(c)
        # Seed demo data if empty
        if c.execute("SELECT COUNT(*) FROM businesses").fetchone()[0] == 0:
            _seed_demo(c)
        # Seed demo events independently; re-seed if all events are in the past
        total_ev = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        future_ev = c.execute("SELECT COUNT(*) FROM events WHERE starts_at >= datetime('now')").fetchone()[0]
        if total_ev == 0 or future_ev == 0:
            _seed_events(c)
        # Seed demo bubbles if none active
        if c.execute("SELECT COUNT(*) FROM life_bubbles WHERE expires_at > datetime('now')").fetchone()[0] == 0:
            _seed_bubbles(c)

def _ensure_demo_token(c):
    """Create demo user + session on every boot if they don't exist."""
    DEMO_TOKEN = "demo-token-konnekt-2026"
    DEMO_EMAIL = "demo@konnekt.app"
    DEMO_USER  = "demo"
    # Create demo user if missing
    existing = c.execute("SELECT id FROM users WHERE email=?", (DEMO_EMAIL,)).fetchone()
    if not existing:
        c.execute(
            "INSERT OR IGNORE INTO users (username,email,password_hash,display_name,city,points_balance,avatar_url) "
            "VALUES (?,?,?,?,?,?,?)",
            (DEMO_USER, DEMO_EMAIL, "DEMO_NO_LOGIN", "Demo-Nutzer", "Bern", 250,
             "https://i.pravatar.cc/150?u=demo@konnekt.app")
        )
        existing = c.execute("SELECT id FROM users WHERE email=?", (DEMO_EMAIL,)).fetchone()
    demo_id = existing["id"]
    # Upsert the demo session token with 1-year expiry
    expires = (datetime.utcnow() + timedelta(days=365)).isoformat()
    c.execute("INSERT OR REPLACE INTO sessions (token,user_id,expires_at) VALUES (?,?,?)",
              (DEMO_TOKEN, demo_id, expires))

def _seed_demo(c):
    # Demo businesses with coupons
    businesses = [
        ("Bäckerei Müller", "Frische Backwaren täglich", "food", "Hauptstrasse 5", "Bern", 46.948, 7.447),
        ("Sport Zentrum Bern", "Fitness & Yoga", "sport", "Spitalgasse 12", "Bern", 46.952, 7.440),
        ("Kulturhaus", "Konzerte & Ausstellungen", "culture", "Kramgasse 8", "Bern", 46.947, 7.451),
        ("Bio Markt", "Regionale Bio-Produkte", "food", "Marktgasse 3", "Bern", 46.950, 7.445),
        ("Kino Rex", "Unabhängiges Kino Bern", "culture", "Schwanengasse 9", "Bern", 46.949, 7.443),
    ]
    for b in businesses:
        c.execute("INSERT INTO businesses (name,description,category,address,city,lat,lng,verified) VALUES (?,?,?,?,?,?,?,1)", b)

    biz_ids = [r[0] for r in c.execute("SELECT id FROM businesses ORDER BY id").fetchall()]
    coupons = [
        (biz_ids[0], "10% auf alle Backwaren", "Zeige diesen Code an der Kasse", 100, "food"),
        (biz_ids[0], "Kaffee gratis zum Gebäck", "Bei jedem Kauf ab 3 CHF", 50, "food"),
        (biz_ids[1], "1 Monat Fitness gratis", "Für Neukunden", 500, "sport"),
        (biz_ids[1], "Einzeleintritt Schwimmbad", "Gültig Mo-Fr", 150, "sport"),
        (biz_ids[2], "Konzert-Ticket 50% Rabatt", "Ausgewählte Veranstaltungen", 200, "culture"),
        (biz_ids[3], "Frische Gemüsebox", "Saisonales Sortiment", 120, "food"),
        (biz_ids[4], "2 Kinokarten zum Preis von 1", "Alle Vorstellungen", 300, "culture"),
    ]
    for cpn in coupons:
        c.execute("INSERT INTO coupons (business_id,title,description,points_cost,category) VALUES (?,?,?,?,?)", cpn)

def _seed_events(c):
    """Seed demo events — hangouts + volunteer — so the map & list are never empty."""
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    # (title, description, category, ev_type, is_public, address, city, lat, lng, pts, max_p, days_ahead, hour)
    evs = [
        ("UNO Spielabend 🃏 — Alle willkommen!",
         "Spontaner UNO-Abend im Rosengarten. Locals, Ausländer, Familien — alle herzlich willkommen! Bring your own snacks.",
         "social","hangout",1,"Rosengarten Bern","Bern",46.9572,7.4542,0,8,1,14),
        ("Brettspiele Café — Offener Tisch 🎲",
         "Komm und spiel mit! Chess, Scrabble, Catan — alle Sprachen ok. Einfach reinkommen.",
         "social","hangout",1,"Münstergasse 38, Bern","Bern",46.9473,7.4500,0,10,1,16),
        ("Improv Theater — Join us! 🎭",
         "Improvisationstheater-Gruppe sucht neue Gesichter. Keine Erfahrung nötig, nur Lust am Spielen!",
         "social","hangout",1,"Dampfzentrale, Bern","Bern",46.9455,7.4633,0,12,2,19),
        ("Deutschkurs für Geflüchtete & Migranten",
         "Kostenloser wöchentlicher Deutschkurs. Alle Niveaus willkommen.",
         "education","volunteer",0,"Heiliggeistkirche, Bern","Bern",46.9481,7.4408,100,20,2,9),
        ("Quartierreinigung Länggasse 🌿",
         "Gemeinsam Müll sammeln und Strassen sauber halten. Material wird gestellt.",
         "environment","volunteer",0,"Länggasse, Bern","Bern",46.9518,7.4196,80,30,3,9),
        ("Senioren-Kaffeenachmittag ☕",
         "Besuche einsame Senioren im Altersheim für 1-2h Gesellschaft, Kaffee & Gespräch.",
         "senior","volunteer",0,"Altersheim Brunnmatt, Bern","Bern",46.9459,7.4127,100,6,3,14),
        ("Park Yoga — Gratis für alle 🧘",
         "Outdoor-Yoga jeden Dienstagmorgen. Keine Vorkenntnisse nötig, Matte mitbringen.",
         "health","volunteer",0,"Bundesgarten, Bern","Bern",46.9433,7.4348,50,20,4,7),
        ("Sprachencafé — Multilingual Meetup 🌍",
         "Treffe Leute aus aller Welt. Übe Deutsch, Englisch, Französisch — alle willkommen!",
         "social","hangout",1,"Café de la Grenette, Bern","Bern",46.9481,7.4476,0,15,4,17),
    ]
    for (title,desc,cat,ev_type,is_pub,addr,city,lat,lng,pts,max_p,days,hour) in evs:
        starts = (now + timedelta(days=days)).replace(hour=hour,minute=0,second=0,microsecond=0)
        try:
            c.execute("""INSERT INTO events
                (organizer_id,title,description,category,type,is_public,address,city,lat,lng,
                 starts_at,points_reward,max_participants,status)
                VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,'active')""",
                (title,desc,cat,ev_type,is_pub,addr,city,lat,lng,
                 starts.strftime('%Y-%m-%dT%H:%M:%S'),pts,max_p))
        except Exception:
            pass

def _seed_bubbles(c):
    """Seed demo life bubbles so the map is alive on first visit."""
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    # Use first available user, or skip if none
    first_user = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if not first_user:
        return
    uid = first_user["id"]
    bubbles = [
        ("UNO am Rosengarten 🃏", "🃏", "Spontane Runde UNO! Platz für 4 mehr. Komm einfach vorbei!", 46.9572, 7.4542, "Rosengarten, Bern", "Bern", 3),
        ("Öffentliches Klavier 🎹", "🎹", "Jemand spielt gerade Klavier im Generationen Haus. Es klingt grandios — komm zuhören oder mitspielen!", 46.9478, 7.4440, "Generationen Haus, Bern", "Bern", 2),
        ("Frisbee im Bundesgarten 🥏", "🥏", "Wir spielen Frisbee, brauchen noch 2-3 Leute!", 46.9433, 7.4348, "Bundesgarten, Bern", "Bern", 2),
        ("Kaffee & Konversation ☕", "☕", "Sitze allein im Café de la Grenette. Wer will reden? Alle Sprachen ok.", 46.9481, 7.4476, "Café de la Grenette, Bern", "Bern", 1),
        ("Skateboard am Bundeshaus 🛹", "🛹", "Learning tricks, chill vibes, all levels welcome!", 46.9466, 7.4438, "Bundeshaus, Bern", "Bern", 4),
    ]
    for (title, emoji, desc, lat, lng, addr, city, hrs) in bubbles:
        expires = (now + timedelta(hours=hrs)).isoformat()
        try:
            c.execute("""INSERT INTO life_bubbles (user_id,title,emoji,description,lat,lng,address,city,expires_at)
                         VALUES (?,?,?,?,?,?,?,?,?)""",
                      (uid, title, emoji, desc, lat, lng, addr, city, expires))
        except Exception:
            pass

def geocode_address(address, city):
    """Use Nominatim (OSM) — free, no API key needed."""
    if not address and not city:
        return 0.0, 0.0
    try:
        query = ", ".join(filter(None, [address, city, "Switzerland"]))
        r = req.get("https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "KonnektApp/2.0"},
            timeout=2)
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return 0.0, 0.0

init_db()

# ── Auth ──────────────────────────────────────────────────────────────────────

def hash_password(pw: str) -> str:
    return hashlib.sha256((pw + SECRET[:16]).encode()).hexdigest()

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization","").replace("Bearer ","")
        if not token:
            return jsonify({"error": "unauthorized"}), 401
        with get_db() as c:
            row = c.execute(
                "SELECT user_id FROM sessions WHERE token=? AND expires_at > datetime('now')", (token,)
            ).fetchone()
        if not row:
            return jsonify({"error": "token invalid or expired"}), 401
        g.user_id = row["user_id"]
        return f(*args, **kwargs)
    return decorated

def award_points(user_id, delta, reason, ref_type=None, ref_id=None):
    with get_db() as c:
        c.execute("UPDATE users SET points_balance = points_balance + ? WHERE id=?", (delta, user_id))
        c.execute("INSERT INTO point_transactions (user_id,delta,reason,ref_type,ref_id) VALUES (?,?,?,?,?)",
                  (user_id, delta, reason, ref_type, ref_id))

# ── Static / Frontend ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    resp = send_from_directory(app.static_folder, "index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/<path:path>")
def static_files(path):
    try:
        resp = send_from_directory(app.static_folder, path)
        if path in ("sw.js", "manifest.json"):
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp
    except Exception:
        resp = send_from_directory(app.static_folder, "index.html")
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

# ── Auth Routes ───────────────────────────────────────────────────────────────

@app.post("/api/auth/register")
def register():
    d = request.json or {}
    username = d.get("username","").strip().lower()
    email    = d.get("email","").strip().lower()
    password = d.get("password","")
    name     = d.get("display_name", username)
    city     = d.get("city","")
    if not username or not email or len(password) < 6:
        return jsonify({"error": "username, email und password (min 6 Zeichen) erforderlich"}), 400
    with get_db() as c:
        try:
            c.execute(
                "INSERT INTO users (username,email,password_hash,display_name,city) VALUES (?,?,?,?,?)",
                (username, email, hash_password(password), name, city)
            )
            user_id = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
            token = secrets.token_urlsafe(32)
            expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
            c.execute("INSERT INTO sessions (token,user_id,expires_at) VALUES (?,?,?)", (token, user_id, expires))
            # Welcome points
            c.execute("UPDATE users SET points_balance=50 WHERE id=?", (user_id,))
            c.execute("INSERT INTO point_transactions (user_id,delta,reason) VALUES (?,50,'Willkommen bei Konnekt!')", (user_id,))
        except sqlite3.IntegrityError:
            return jsonify({"error": "Username oder E-Mail bereits vergeben"}), 409
    return jsonify({"token": token, "user_id": user_id, "points": 50}), 201

@app.post("/api/auth/login")
def login():
    # Simple rate limiter: max 10 attempts per IP per minute
    ip = request.remote_addr or "unknown"
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < 60]
    if len(_login_attempts[ip]) >= 10:
        return jsonify({"error": "Zu viele Versuche. Bitte 1 Minute warten."}), 429
    _login_attempts[ip].append(now)

    d = request.json or {}
    email = d.get("email","").strip().lower()
    password = d.get("password","")
    with get_db() as c:
        user = c.execute(
            "SELECT id,username,display_name,points_balance FROM users WHERE email=? AND password_hash=?",
            (email, hash_password(password))
        ).fetchone()
        if not user:
            return jsonify({"error": "Falsche E-Mail oder Passwort"}), 401
        token = secrets.token_urlsafe(32)
        expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
        c.execute("INSERT INTO sessions (token,user_id,expires_at) VALUES (?,?,?)", (token, user["id"], expires))
    return jsonify({"token": token, "user": dict(user)})

@app.get("/api/auth/me")
@require_auth
def me():
    with get_db() as c:
        user = c.execute(
            "SELECT id,username,display_name,bio,avatar_url,city,points_balance,volunteer_hours,is_senior,is_verified,subscription_tier FROM users WHERE id=?",
            (g.user_id,)
        ).fetchone()
    return jsonify(dict(user))

@app.post("/api/auth/logout")
@require_auth
def logout_api():
    token = request.headers.get("Authorization","").replace("Bearer ","")
    with get_db() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))
    return jsonify({"ok": True})

# ── Google OAuth SSO ──────────────────────────────────────────────────────────

@app.get("/api/auth/google")
def google_auth_start():
    if not GOOGLE_CLIENT_ID:
        return redirect("/?error=google_not_configured")
    redirect_uri = request.host_url.rstrip('/') + "/api/auth/google/callback"
    state = secrets.token_urlsafe(16)
    params = urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })
    return redirect(f"{GOOGLE_AUTH_URL}?{params}")

@app.get("/api/auth/google/callback")
def google_auth_callback():
    code = request.args.get("code","")
    if not code:
        return redirect("/?sso_error=google_denied")
    redirect_uri = request.host_url.rstrip('/') + "/api/auth/google/callback"
    try:
        token_resp = req.post(GOOGLE_TOKEN_URL, data={
            "code": code, "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code"
        }, timeout=10).json()
        access_token = token_resp.get("access_token","")
        if not access_token:
            return redirect("/?sso_error=google_token_failed")
        info = req.get(GOOGLE_INFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10).json()
        email = info.get("email","").lower()
        name  = info.get("name","")
        pic   = info.get("picture","")
        if not email:
            return redirect("/?sso_error=no_email")
    except Exception:
        return redirect("/?sso_error=google_error")
    with get_db() as c:
        user = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if not user:
            base = email.split("@")[0].lower()[:18]
            uname = base; i = 2
            while c.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone():
                uname = f"{base}{i}"; i += 1
            c.execute(
                "INSERT INTO users (username,email,password_hash,display_name,avatar_url,is_verified,points_balance) VALUES (?,?,?,?,?,1,50)",
                (uname, email, "OAUTH_GOOGLE", name or uname, pic)
            )
            uid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.execute("INSERT INTO point_transactions (user_id,delta,reason) VALUES (?,50,'Willkommen via Google!')", (uid,))
        else:
            uid = user["id"]
            if pic:
                c.execute("UPDATE users SET avatar_url=? WHERE id=? AND (avatar_url='' OR avatar_url IS NULL)", (pic, uid))
        sso_token = secrets.token_urlsafe(32)
        expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
        c.execute("INSERT INTO sessions (token,user_id,expires_at) VALUES (?,?,?)", (sso_token, uid, expires))
    return redirect(f"/?sso_token={sso_token}")

# ── Magic Link (passwordless) ─────────────────────────────────────────────────

@app.post("/api/auth/magic")
def request_magic():
    email = (request.json or {}).get("email","").strip().lower()
    if not email or "@" not in email:
        return jsonify({"error": "Gültige E-Mail erforderlich"}), 400
    code = secrets.token_urlsafe(32)
    _magic_links[code] = {"email": email, "expires": time.time() + 900}
    magic_url = request.host_url.rstrip('/') + f"/api/auth/magic/verify?t={code}"
    # In production: send via email (Mailgun/SendGrid). For beta: log to console.
    print(f"[MAGIC LINK] {email} → {magic_url}", flush=True)
    # Also try to send a basic email if SMTP is configured
    _try_send_magic_email(email, magic_url)
    return jsonify({"ok": True, "dev_url": magic_url if os.getenv("FLASK_ENV") == "development" else None})

def _try_send_magic_email(email, url):
    """Send magic link via email if MAILGUN_API_KEY is set."""
    key = os.getenv("MAILGUN_API_KEY","")
    domain = os.getenv("MAILGUN_DOMAIN","")
    if not key or not domain:
        return
    try:
        req.post(f"https://api.mailgun.net/v3/{domain}/messages",
            auth=("api", key),
            data={"from": f"Konnekt <noreply@{domain}>", "to": email,
                  "subject": "Dein Konnekt Magic Link 🌐",
                  "text": f"Klick hier um dich anzumelden (15 Minuten gültig):\n\n{url}\n\nFalls du das nicht angefordert hast, ignoriere diese E-Mail."},
            timeout=5)
    except Exception:
        pass

@app.get("/api/auth/magic/verify")
def verify_magic():
    code = request.args.get("t","")
    data = _magic_links.pop(code, None)
    if not data or time.time() > data["expires"]:
        return redirect("/?sso_error=link_expired")
    email = data["email"]
    with get_db() as c:
        user = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if not user:
            base = email.split("@")[0].lower()[:18]
            uname = base; i = 2
            while c.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone():
                uname = f"{base}{i}"; i += 1
            c.execute("INSERT INTO users (username,email,password_hash,display_name,points_balance) VALUES (?,?,?,?,50)",
                      (uname, email, "MAGIC_LINK", uname))
            uid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            uid = user["id"]
        sso_token = secrets.token_urlsafe(32)
        expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
        c.execute("INSERT INTO sessions (token,user_id,expires_at) VALUES (?,?,?)", (sso_token, uid, expires))
    return redirect(f"/?sso_token={sso_token}")

# ── Subscriptions & Business Model ───────────────────────────────────────────

def get_user_tier(user_id):
    with get_db() as c:
        row = c.execute("SELECT subscription_tier FROM users WHERE id=?", (user_id,)).fetchone()
        return (row["subscription_tier"] or "free") if row else "free"

@app.get("/api/subscription")
@require_auth
def get_subscription():
    with get_db() as c:
        sub = c.execute("SELECT * FROM subscriptions WHERE user_id=?", (g.user_id,)).fetchone()
        tier = get_user_tier(g.user_id)
    return jsonify({
        "tier": tier,
        "subscription": dict(sub) if sub else None,
        "perks": TIER_PERKS.get(tier, TIER_PERKS["free"])
    })

TIER_PERKS = {
    "free":     {"label": "Free", "color": "#64748b", "badge": "",
                 "features": ["Events mitmachen", "Gute Taten eintragen", "Zeitbank", "Coupons einlösen"]},
    "pro":      {"label": "Pro", "color": "#a78bfa", "badge": "⭐",
                 "features": ["Alles aus Free", "✅ Verifiziert-Badge", "📊 Impact-Analyse", "🔝 Priorität in Suche", "🎯 Unbegrenzte Events", "💬 Priority-Support"]},
    "business": {"label": "Business Partner", "color": "#f59e0b", "badge": "🏢",
                 "features": ["Alles aus Pro", "🎟️ Eigene Coupons verwalten", "📣 Featured Events", "📈 Volunteer-Tracking", "📋 Monats-Impact-Report", "🤝 Partnerseite"]},
    "ngo":      {"label": "NGO Partner", "color": "#10b981", "badge": "🌱",
                 "features": ["Alles aus Business", "🆓 Kostenlos für NGOs", "🏆 NGO-Leaderboard", "📧 Direktkontakt zu Volunteers"]}
}

STRIPE_PRICES = {
    "pro":      {"monthly_chf": 9,  "annual_chf": 79,  "description": "Für engagierte Einzelpersonen"},
    "business": {"monthly_chf": 49, "annual_chf": 449, "description": "Für Unternehmen & Vereine"},
}

@app.post("/api/subscription/upgrade")
@require_auth
def upgrade_subscription():
    tier = (request.json or {}).get("tier","pro")
    if tier not in ("pro","business"):
        return jsonify({"error": "invalid tier"}), 400
    if not STRIPE_SECRET_KEY:
        # No Stripe configured: grant tier for free (beta/demo)
        with get_db() as c:
            c.execute("UPDATE users SET subscription_tier=? WHERE id=?", (tier, g.user_id))
            existing = c.execute("SELECT id FROM subscriptions WHERE user_id=?", (g.user_id,)).fetchone()
            if existing:
                c.execute("UPDATE subscriptions SET tier=? WHERE user_id=?", (tier, g.user_id))
            else:
                c.execute("INSERT INTO subscriptions (user_id,tier) VALUES (?,?)", (g.user_id, tier))
        return jsonify({"ok": True, "tier": tier, "method": "beta_free"})
    # With Stripe: create checkout session
    price_id = STRIPE_PRO_PRICE_ID if tier == "pro" else STRIPE_BUSINESS_PRICE_ID
    try:
        checkout = req.post("https://api.stripe.com/v1/checkout/sessions",
            headers={"Authorization": f"Bearer {STRIPE_SECRET_KEY}"},
            data={
                "mode": "subscription",
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
                "success_url": request.host_url + "?upgrade_success=1",
                "cancel_url": request.host_url + "?upgrade_cancelled=1",
                "metadata[user_id]": str(g.user_id),
                "metadata[tier]": tier,
            }, timeout=10
        ).json()
        if "url" not in checkout:
            return jsonify({"error": "Stripe error", "detail": checkout.get("error",{})}), 500
        return jsonify({"checkout_url": checkout["url"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/subscription/stripe-webhook")
def stripe_webhook():
    """Handle Stripe webhook to activate subscriptions after payment."""
    payload = request.data
    sig = request.headers.get("Stripe-Signature","")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET","")
    # Basic event parsing (full signature verification needs stripe-python library)
    try:
        event = json.loads(payload)
    except Exception:
        return jsonify({"error": "invalid json"}), 400
    if event.get("type") == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = int(session.get("metadata",{}).get("user_id",0))
        tier    = session.get("metadata",{}).get("tier","pro")
        stripe_customer = session.get("customer","")
        stripe_sub = session.get("subscription","")
        if user_id:
            with get_db() as c:
                c.execute("UPDATE users SET subscription_tier=? WHERE id=?", (tier, user_id))
                existing = c.execute("SELECT id FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
                if existing:
                    c.execute("UPDATE subscriptions SET tier=?,stripe_customer_id=?,stripe_subscription_id=? WHERE user_id=?",
                              (tier, stripe_customer, stripe_sub, user_id))
                else:
                    c.execute("INSERT INTO subscriptions (user_id,tier,stripe_customer_id,stripe_subscription_id) VALUES (?,?,?,?)",
                              (user_id, tier, stripe_customer, stripe_sub))
    return jsonify({"ok": True})

@app.get("/api/analytics/impact")
@require_auth
def impact_analytics():
    tier = get_user_tier(g.user_id)
    if tier not in ("pro","business","ngo"):
        return jsonify({"error": "Pro required", "upgrade": True}), 403
    with get_db() as c:
        total_pts   = c.execute("SELECT SUM(delta) FROM point_transactions WHERE user_id=? AND delta>0", (g.user_id,)).fetchone()[0] or 0
        deeds_count = c.execute("SELECT COUNT(*) FROM good_deeds WHERE user_id=?", (g.user_id,)).fetchone()[0]
        events_done = c.execute("SELECT COUNT(*) FROM event_registrations WHERE user_id=? AND status='completed'", (g.user_id,)).fetchone()[0]
        events_made = c.execute("SELECT COUNT(*) FROM events WHERE organizer_id=?", (g.user_id,)).fetchone()[0]
        visits_done = c.execute("SELECT COUNT(*) FROM senior_visits WHERE visitor_id=? AND completed=1", (g.user_id,)).fetchone()[0]
        monthly = c.execute("""
            SELECT strftime('%Y-%m', created_at) as month, SUM(delta) as pts
            FROM point_transactions WHERE user_id=? AND delta>0
            GROUP BY month ORDER BY month DESC LIMIT 6""", (g.user_id,)).fetchall()
    co2_saved = round(events_done * 2.1 + deeds_count * 0.5, 1)
    return jsonify({
        "total_points_earned": total_pts,
        "deeds": deeds_count,
        "events_completed": events_done,
        "events_organized": events_made,
        "senior_visits": visits_done,
        "co2_kg_saved_equiv": co2_saved,
        "volunteer_hours_equiv": round(events_done * 2 + deeds_count * 0.5),
        "monthly_breakdown": [dict(r) for r in monthly],
    })

# ── Legal Request (address on request) ───────────────────────────────────────

@app.post("/api/legal/address-request")
def legal_address_request():
    d = request.json or {}
    name  = d.get("name","").strip()
    org   = d.get("org","").strip()
    email = d.get("email","").strip().lower()
    purpose = d.get("purpose","").strip()
    if not name or not email or not purpose:
        return jsonify({"error": "Name, E-Mail und Zweck erforderlich"}), 400
    with get_db() as c:
        c.execute("INSERT INTO legal_requests (requester_name,requester_org,requester_email,purpose) VALUES (?,?,?,?)",
                  (name, org, email, purpose))
        req_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Notify owner
    _try_send_magic_email.__wrapped__ = None  # reuse send helper
    owner_msg = f"Neue Adressanfrage #{req_id}\nVon: {name} ({org})\nE-Mail: {email}\nZweck: {purpose}"
    print(f"[LEGAL REQUEST] {owner_msg}", flush=True)
    return jsonify({"ok": True, "request_id": req_id,
                    "message": "Ihre Anfrage wurde registriert. Bei berechtigtem Interesse erhalten Sie innerhalb von 14 Tagen eine Antwort."})

# ── Events (VolunteerHub) ─────────────────────────────────────────────────────

@app.get("/api/events")
def get_events():
    city     = request.args.get("city","")
    category = request.args.get("category","")
    ev_type  = request.args.get("type","")
    limit    = int(request.args.get("limit", 20))
    with get_db() as c:
        q = "SELECT e.*, u.display_name as organizer_name, u.is_verified as org_verified FROM events e JOIN users u ON e.organizer_id=u.id WHERE e.status='active' AND e.starts_at >= datetime('now', '-2 hours')"
        params = []
        if city:
            q += " AND e.city LIKE ?"; params.append(f"%{city}%")
        if category:
            q += " AND e.category=?"; params.append(category)
        if ev_type:
            q += " AND e.type=?"; params.append(ev_type)
        q += " ORDER BY e.starts_at ASC LIMIT ?"
        params.append(limit)
        rows = c.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/events/<int:eid>")
def get_event(eid):
    with get_db() as c:
        ev = c.execute("SELECT e.*, u.display_name as organizer_name FROM events e JOIN users u ON e.organizer_id=u.id WHERE e.id=?", (eid,)).fetchone()
        if not ev:
            return jsonify({"error": "not found"}), 404
        regs = c.execute("SELECT u.display_name, u.avatar_url FROM event_registrations er JOIN users u ON er.user_id=u.id WHERE er.event_id=? LIMIT 20", (eid,)).fetchall()
    result = dict(ev)
    result["attendees"] = [dict(r) for r in regs]
    return jsonify(result)

@app.post("/api/events")
@require_auth
def create_event():
    d = request.json or {}
    required = ["title", "starts_at"]
    if not all(d.get(k) for k in required):
        return jsonify({"error": "title und starts_at erforderlich"}), 400
    lat = float(d.get("lat") or 0)
    lng = float(d.get("lng") or 0)
    if not lat or not lng:
        lat, lng = geocode_address(d.get("address",""), d.get("city",""))
    ev_type = d.get("type", "volunteer")
    is_pub  = 1 if ev_type == "hangout" else 0
    with get_db() as c:
        c.execute("""
            INSERT INTO events (organizer_id,title,description,category,type,is_public,address,city,lat,lng,starts_at,ends_at,max_participants,points_reward,tags)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            g.user_id, d["title"], d.get("description",""), d.get("category","other"),
            ev_type, is_pub,
            d.get("address",""), d.get("city",""), lat, lng,
            d["starts_at"], d.get("ends_at"), d.get("max_participants",0),
            d.get("points_reward",50), json.dumps(d.get("tags",[]))
        ))
        eid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    award_points(g.user_id, 20, "Event erstellt", "event", eid)
    return jsonify({"id": eid, "ok": True}), 201

@app.post("/api/events/<int:eid>/register")
@require_auth
def register_event(eid):
    with get_db() as c:
        ev = c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        if not ev:
            return jsonify({"error": "not found"}), 404
        if ev["organizer_id"] == g.user_id:
            return jsonify({"error": "Du bist der Organisator dieses Events"}), 409
        already = c.execute("SELECT id FROM event_registrations WHERE event_id=? AND user_id=?", (eid, g.user_id)).fetchone()
        if already:
            return jsonify({"error": "bereits angemeldet"}), 409
        if ev["max_participants"] > 0 and ev["participants_count"] >= ev["max_participants"]:
            return jsonify({"error": "ausgebucht"}), 409
        c.execute("INSERT INTO event_registrations (event_id,user_id) VALUES (?,?)", (eid, g.user_id))
        c.execute("UPDATE events SET participants_count=participants_count+1 WHERE id=?", (eid,))
    award_points(g.user_id, 10, "Event-Anmeldung", "event", eid)
    return jsonify({"ok": True})

@app.post("/api/events/<int:eid>/complete")
@require_auth
def complete_event(eid):
    """Mark attendance and award full points — only callable after event starts."""
    with get_db() as c:
        reg = c.execute("SELECT * FROM event_registrations WHERE event_id=? AND user_id=?", (eid, g.user_id)).fetchone()
        if not reg:
            return jsonify({"error": "nicht angemeldet"}), 404
        if reg["status"] == "completed":
            return jsonify({"error": "bereits abgeschlossen"}), 409
        ev = c.execute("SELECT points_reward, starts_at FROM events WHERE id=?", (eid,)).fetchone()
        if ev and ev["starts_at"] > datetime.utcnow().isoformat():
            return jsonify({"error": "Event hat noch nicht begonnen"}), 409
        pts = ev["points_reward"] if ev else 50
        c.execute("UPDATE event_registrations SET status='completed', points_awarded=? WHERE event_id=? AND user_id=?", (pts, eid, g.user_id))
        c.execute("UPDATE users SET volunteer_hours=volunteer_hours+2 WHERE id=?", (g.user_id,))
    award_points(g.user_id, pts, "Event abgeschlossen", "event", eid)
    return jsonify({"ok": True, "points_awarded": pts})

@app.post("/api/events/<int:eid>/join-request")
@require_auth
def send_join_request(eid):
    """Request to join a hangout event — queued, host accepts/declines."""
    d = request.json or {}
    with get_db() as c:
        ev = c.execute("SELECT * FROM events WHERE id=? AND status='active'", (eid,)).fetchone()
        if not ev:
            return jsonify({"error": "not found"}), 404
        pos = (c.execute("SELECT COUNT(*) FROM event_join_requests WHERE event_id=? AND status='pending'", (eid,)).fetchone()[0] or 0) + 1
        try:
            c.execute("INSERT INTO event_join_requests (event_id,user_id,queue_position,message) VALUES (?,?,?,?)",
                      (eid, g.user_id, pos, (d.get("message") or "").strip()[:200]))
        except sqlite3.IntegrityError:
            return jsonify({"error": "Anfrage bereits gesendet"}), 409
    return jsonify({"ok": True, "queue_position": pos})

@app.get("/api/events/<int:eid>/join-requests")
@require_auth
def get_join_requests(eid):
    """Host sees pending join requests for their event."""
    with get_db() as c:
        ev = c.execute("SELECT organizer_id FROM events WHERE id=?", (eid,)).fetchone()
        if not ev or ev["organizer_id"] != g.user_id:
            return jsonify({"error": "forbidden"}), 403
        rows = c.execute("""
            SELECT jq.id, jq.queue_position, jq.message, jq.status, jq.created_at,
                   u.id as user_id, u.display_name, u.avatar_url, u.city, u.volunteer_hours
            FROM event_join_requests jq JOIN users u ON jq.user_id=u.id
            WHERE jq.event_id=? AND jq.status='pending'
            ORDER BY jq.queue_position ASC
        """, (eid,)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/events/<int:eid>/join-requests/<int:rid>/respond")
@require_auth
def respond_join_request(eid, rid):
    """Host accepts or declines a join request."""
    action = (request.json or {}).get("action","")
    if action not in ("accept","decline"):
        return jsonify({"error": "action must be 'accept' or 'decline'"}), 400
    with get_db() as c:
        ev = c.execute("SELECT organizer_id FROM events WHERE id=?", (eid,)).fetchone()
        if not ev or ev["organizer_id"] != g.user_id:
            return jsonify({"error": "forbidden"}), 403
        jq = c.execute("SELECT * FROM event_join_requests WHERE id=? AND event_id=?", (rid, eid)).fetchone()
        if not jq:
            return jsonify({"error": "not found"}), 404
        new_status = "accepted" if action == "accept" else "declined"
        c.execute("UPDATE event_join_requests SET status=? WHERE id=?", (new_status, rid))
        if action == "accept":
            try:
                c.execute("INSERT INTO event_registrations (event_id,user_id) VALUES (?,?)", (eid, jq["user_id"]))
                c.execute("UPDATE events SET participants_count=participants_count+1 WHERE id=?", (eid,))
            except sqlite3.IntegrityError:
                pass
            award_points(jq["user_id"], 10, "Hangout-Anfrage akzeptiert", "event", eid)
    return jsonify({"ok": True, "action": action})

@app.get("/api/map/events")
def map_events():
    """Events with GPS coords for map display."""
    city = request.args.get("city","")
    with get_db() as c:
        q = """SELECT id, title, description, category, type, is_public, address, city,
                      lat, lng, starts_at, max_participants, participants_count, points_reward
               FROM events WHERE status='active' AND lat != 0 AND lng != 0"""
        params = []
        if city:
            q += " AND city LIKE ?"; params.append(f"%{city}%")
        q += " ORDER BY starts_at ASC LIMIT 80"
        rows = c.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows])

# ── Life Bubbles ──────────────────────────────────────────────────────────────

@app.get("/api/bubbles")
def get_bubbles():
    """Active life bubbles — spontaneous moments on the map."""
    city = request.args.get("city", "")
    with get_db() as c:
        q = """SELECT b.id, b.title, b.emoji, b.description, b.lat, b.lng,
                      b.address, b.city, b.expires_at, b.created_at,
                      u.display_name, u.avatar_url
               FROM life_bubbles b JOIN users u ON b.user_id=u.id
               WHERE b.expires_at > datetime('now')"""
        params = []
        if city:
            q += " AND b.city LIKE ?"; params.append(f"%{city}%")
        q += " ORDER BY b.created_at DESC LIMIT 60"
        rows = c.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/bubbles")
@require_auth
def drop_bubble():
    """Drop a life bubble — a spontaneous moment others can join."""
    d = request.json or {}
    if not d.get("title"):
        return jsonify({"error": "title required"}), 400
    lat = float(d.get("lat") or 0)
    lng = float(d.get("lng") or 0)
    if not lat or not lng:
        lat, lng = geocode_address(d.get("address", ""), d.get("city", ""))
    hours = min(max(int(d.get("hours", 3)), 1), 8)
    expires = (datetime.utcnow() + timedelta(hours=hours)).isoformat()
    with get_db() as c:
        c.execute("""
            INSERT INTO life_bubbles (user_id, title, emoji, description, lat, lng, address, city, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (g.user_id, d["title"][:100], d.get("emoji", "✨"),
              d.get("description", "")[:200],
              lat, lng, d.get("address", ""), d.get("city", ""), expires))
        bid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return jsonify({"id": bid, "ok": True}), 201

@app.delete("/api/bubbles/<int:bid>")
@require_auth
def delete_bubble(bid):
    with get_db() as c:
        b = c.execute("SELECT user_id FROM life_bubbles WHERE id=?", (bid,)).fetchone()
        if not b:
            return jsonify({"error": "not found"}), 404
        if b["user_id"] != g.user_id:
            return jsonify({"error": "forbidden"}), 403
        c.execute("DELETE FROM life_bubbles WHERE id=?", (bid,))
    return jsonify({"ok": True})

# ── Dashboard Analytics ───────────────────────────────────────────────────────

@app.get("/api/dashboard")
def get_dashboard():
    """Rich stats for the dashboard — charts, category breakdown, trends."""
    with get_db() as c:
        # Category breakdown for events
        cat_rows = c.execute("""
            SELECT category, COUNT(*) as cnt
            FROM events WHERE status='active'
            GROUP BY category ORDER BY cnt DESC LIMIT 8
        """).fetchall()

        # Deeds per day — last 7 days
        deed_rows = c.execute("""
            SELECT date(created_at) as day, COUNT(*) as cnt
            FROM good_deeds
            WHERE created_at >= date('now', '-6 days')
            GROUP BY date(created_at) ORDER BY day ASC
        """).fetchall()
        # Fill in missing days with 0
        from datetime import date, timedelta as td
        days_map = {r["day"]: r["cnt"] for r in deed_rows}
        weekly_deeds = []
        for i in range(6, -1, -1):
            d = (date.today() - td(days=i)).isoformat()
            weekly_deeds.append({"day": d, "count": days_map.get(d, 0)})

        # Event registrations per day — last 7 days
        reg_rows = c.execute("""
            SELECT date(created_at) as day, COUNT(*) as cnt
            FROM event_registrations
            WHERE created_at >= date('now', '-6 days')
            GROUP BY date(created_at) ORDER BY day ASC
        """).fetchall()
        reg_map = {r["day"]: r["cnt"] for r in reg_rows}
        weekly_regs = []
        for i in range(6, -1, -1):
            d = (date.today() - td(days=i)).isoformat()
            weekly_regs.append({"day": d, "count": reg_map.get(d, 0)})

        # Total stats
        stats = c.execute("""
            SELECT
                (SELECT COUNT(*) FROM users) as users,
                (SELECT COUNT(*) FROM good_deeds) as deeds,
                (SELECT COUNT(*) FROM events WHERE status='active') as active_events,
                (SELECT COUNT(*) FROM event_registrations) as total_signups,
                (SELECT COALESCE(SUM(points_earned),0) FROM good_deeds) as deed_pts,
                (SELECT COUNT(*) FROM life_bubbles WHERE expires_at > datetime('now')) as live_bubbles
        """).fetchone()

        return jsonify({
            "categories": [{"name": r["category"], "count": r["cnt"]} for r in cat_rows],
            "weekly_deeds": weekly_deeds,
            "weekly_regs": weekly_regs,
            "users": stats["users"],
            "deeds": stats["deeds"],
            "active_events": stats["active_events"],
            "total_signups": stats["total_signups"],
            "live_bubbles": stats["live_bubbles"],
        })

# ── Coupons ───────────────────────────────────────────────────────────────────

@app.get("/api/coupons")
def get_coupons():
    category = request.args.get("category","")
    city = request.args.get("city","")
    with get_db() as c:
        q = """SELECT c.*, b.name as business_name, b.logo_url, b.city as business_city
               FROM coupons c JOIN businesses b ON c.business_id=b.id
               WHERE c.status='active' AND (c.max_redemptions=0 OR c.redemptions_count < c.max_redemptions)"""
        params = []
        if category:
            q += " AND c.category=?"; params.append(category)
        if city:
            q += " AND b.city LIKE ?"; params.append(f"%{city}%")
        q += " ORDER BY c.points_cost ASC"
        rows = c.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/coupons/<int:cid>/redeem")
@require_auth
def redeem_coupon(cid):
    with get_db() as c:
        cpn = c.execute("SELECT * FROM coupons WHERE id=?", (cid,)).fetchone()
        if not cpn:
            return jsonify({"error": "not found"}), 404
        if cpn["status"] != "active":
            return jsonify({"error": "Coupon nicht mehr verfügbar"}), 409
        if cpn["max_redemptions"] > 0 and cpn["redemptions_count"] >= cpn["max_redemptions"]:
            return jsonify({"error": "Coupon ausgeschöpft"}), 409
        # One redemption per user per coupon
        already = c.execute("SELECT id FROM coupon_redemptions WHERE coupon_id=? AND user_id=?", (cid, g.user_id)).fetchone()
        if already:
            return jsonify({"error": "Du hast diesen Coupon bereits eingelöst"}), 409
        user = c.execute("SELECT points_balance FROM users WHERE id=?", (g.user_id,)).fetchone()
        if user["points_balance"] < cpn["points_cost"]:
            return jsonify({"error": "nicht genug Punkte", "have": user["points_balance"], "need": cpn["points_cost"]}), 402
        qr = secrets.token_urlsafe(16)
        c.execute("INSERT INTO coupon_redemptions (coupon_id,user_id,qr_code) VALUES (?,?,?)", (cid, g.user_id, qr))
        c.execute("UPDATE users SET points_balance=points_balance-? WHERE id=?", (cpn["points_cost"], g.user_id))
        c.execute("UPDATE coupons SET redemptions_count=redemptions_count+1 WHERE id=?", (cid,))
        c.execute("INSERT INTO point_transactions (user_id,delta,reason,ref_type,ref_id) VALUES (?,?,?,?,?)",
                  (g.user_id, -cpn["points_cost"], f"Coupon eingelöst: {cpn['title']}", "coupon", cid))
    return jsonify({"ok": True, "qr_code": qr, "title": cpn["title"]})

@app.get("/api/my/coupons")
@require_auth
def my_coupons():
    with get_db() as c:
        rows = c.execute("""
            SELECT cr.*, c.title, c.description, b.name as business_name
            FROM coupon_redemptions cr
            JOIN coupons c ON cr.coupon_id=c.id
            JOIN businesses b ON c.business_id=b.id
            WHERE cr.user_id=? ORDER BY cr.redeemed_at DESC
        """, (g.user_id,)).fetchall()
    return jsonify([dict(r) for r in rows])

# ── Nahbar (Anti-Loneliness) ───────────────────────────────────────────────────

@app.get("/api/nahbar/nearby")
@require_auth
def nearby_users():
    """Find users in same city for connection"""
    with get_db() as c:
        user = c.execute("SELECT city FROM users WHERE id=?", (g.user_id,)).fetchone()
        if not user or not user["city"]:
            return jsonify([])
        rows = c.execute("""
            SELECT id, display_name, bio, avatar_url, city, is_senior, volunteer_hours
            FROM users
            WHERE city LIKE ? AND id != ?
            ORDER BY RANDOM() LIMIT 20
        """, (f"%{user['city']}%", g.user_id)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/nahbar/seniors")
@require_auth
def available_seniors():
    """Seniors who want visitors"""
    with get_db() as c:
        rows = c.execute("""
            SELECT id, display_name, city, bio
            FROM users WHERE is_senior=1 AND needs_visitor=1
            ORDER BY RANDOM() LIMIT 10
        """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/nahbar/connect")
@require_auth
def connect_neighbor():
    d = request.json or {}
    target_id = d.get("user_id")
    conn_type = d.get("type", "friend")
    if not target_id:
        return jsonify({"error": "user_id erforderlich"}), 400
    user_a, user_b = min(g.user_id, target_id), max(g.user_id, target_id)
    with get_db() as c:
        try:
            c.execute("INSERT INTO neighbor_connections (user_a,user_b,connection_type) VALUES (?,?,?)",
                      (user_a, user_b, conn_type))
        except sqlite3.IntegrityError:
            return jsonify({"error": "Verbindung existiert bereits"}), 409
    award_points(g.user_id, 15, "Neue Nachbar-Verbindung", "connection", target_id)
    return jsonify({"ok": True})

@app.post("/api/nahbar/visit")
@require_auth
def schedule_visit():
    d = request.json or {}
    senior_id = d.get("senior_id")
    scheduled_at = d.get("scheduled_at")
    if not senior_id or not scheduled_at:
        return jsonify({"error": "senior_id und scheduled_at erforderlich"}), 400
    with get_db() as c:
        c.execute("INSERT INTO senior_visits (senior_id,visitor_id,scheduled_at,duration_min,note) VALUES (?,?,?,?,?)",
                  (senior_id, g.user_id, scheduled_at, d.get("duration_min",60), d.get("note","")))
        vid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    award_points(g.user_id, 5, "Besuch geplant", "visit", vid)
    return jsonify({"ok": True, "id": vid})

@app.post("/api/nahbar/visit/<int:vid>/complete")
@require_auth
def complete_visit(vid):
    with get_db() as c:
        v = c.execute("SELECT * FROM senior_visits WHERE id=? AND visitor_id=?", (vid, g.user_id)).fetchone()
        if not v:
            return jsonify({"error": "not found"}), 404
        c.execute("UPDATE senior_visits SET completed=1, points_awarded=100 WHERE id=?", (vid,))
    award_points(g.user_id, 100, "Senior-Besuch abgeschlossen", "visit", vid)
    return jsonify({"ok": True, "points_awarded": 100})

@app.post("/api/good-deed")
@require_auth
def log_good_deed():
    d = request.json or {}
    category = d.get("category","neighbor")
    description = d.get("description","").strip()
    if not description:
        return jsonify({"error": "description erforderlich"}), 400
    with get_db() as c:
        # Anti-cheat: max 5 good deeds per day per user
        today_count = c.execute(
            "SELECT COUNT(*) FROM good_deeds WHERE user_id=? AND date(created_at)=date('now')",
            (g.user_id,)
        ).fetchone()[0]
        if today_count >= 5:
            return jsonify({"error": "Tageslimit erreicht (5 Taten/Tag). Morgen geht's weiter! 🌱"}), 429
        c.execute("INSERT INTO good_deeds (user_id,category,description,points_earned) VALUES (?,?,?,25)",
                  (g.user_id, category, description))
        did = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    award_points(g.user_id, 25, "Gute Tat", "deed", did)
    return jsonify({"ok": True, "points_earned": 25})

@app.get("/api/good-deeds/feed")
def good_deeds_feed():
    city = request.args.get("city","")
    with get_db() as c:
        q = "SELECT gd.*, u.display_name, u.city FROM good_deeds gd JOIN users u ON gd.user_id=u.id WHERE 1=1"
        params = []
        if city:
            q += " AND u.city LIKE ?"; params.append(f"%{city}%")
        q += " ORDER BY gd.created_at DESC LIMIT 30"
        rows = c.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows])

# ── Activity Suggestions (AI context-aware) ───────────────────────────────────

ACTIVITY_DB = [
    {"category":"outdoor","title":"Stadtspaziergang mit Nachbarn","desc":"30 min gemeinsam durch das Quartier, neue Ecken entdecken","season":"all"},
    {"category":"social","title":"Kaffee-Runde organisieren","desc":"Lade 3-5 Nachbarn zum Kaffee ein","season":"all"},
    {"category":"volunteer","title":"Gemeinschaftsgarten helfen","desc":"2 Stunden im lokalen Garten mithelfen","season":"spring,summer"},
    {"category":"senior","title":"Senior beim Einkaufen begleiten","desc":"Begleite jemanden älteren zum wöchentlichen Einkauf","season":"all"},
    {"category":"outdoor","title":"Fahrradtour ins Grüne","desc":"Gemeinsame Radtour mit Picknick","season":"spring,summer,fall"},
    {"category":"social","title":"Spieleabend organisieren","desc":"Brett- oder Kartenspiele mit Nachbarn","season":"all"},
    {"category":"volunteer","title":"Müll im Quartier sammeln","desc":"1 Stunde sauber machen, Community stärken","season":"all"},
    {"category":"senior","title":"Vorlesen oder Musik hören","desc":"Besuche jemanden für 1h kulturellen Austausch","season":"all"},
    {"category":"outdoor","title":"Naturbeobachtung","desc":"Vögel, Pflanzen beobachten — Handy weglegen","season":"spring,summer"},
    {"category":"social","title":"Gemeinschaftskochen","desc":"Koche mit Nachbarn und teile das Essen","season":"all"},
    {"category":"volunteer","title":"Fahrradwerkstatt helfen","desc":"Repariere Fahrräder für Bedürftige","season":"all"},
    {"category":"social","title":"Sprachentausch","desc":"Biete deine Sprachkenntnisse an, lerne dafür eine andere","season":"all"},
]

@app.get("/api/activities/suggest")
def suggest_activities():
    category = request.args.get("category","")
    limit = int(request.args.get("limit",5))
    import random
    acts = ACTIVITY_DB.copy()
    if category:
        acts = [a for a in acts if a["category"] == category]
    random.shuffle(acts)
    return jsonify(acts[:limit])

# ── Profile + Points ──────────────────────────────────────────────────────────

@app.get("/api/profile/<int:uid>")
def get_profile(uid):
    with get_db() as c:
        user = c.execute("""SELECT id,username,display_name,bio,avatar_url,city,
            points_balance,volunteer_hours,is_senior,is_verified,is_ngo,created_at FROM users WHERE id=?""", (uid,)).fetchone()
        if not user:
            return jsonify({"error": "not found"}), 404
        deeds_count = c.execute("SELECT COUNT(*) FROM good_deeds WHERE user_id=?", (uid,)).fetchone()[0]
        events_done = c.execute("SELECT COUNT(*) FROM event_registrations WHERE user_id=? AND status='completed'", (uid,)).fetchone()[0]
    result = dict(user)
    result["deeds_count"] = deeds_count
    result["events_completed"] = events_done
    return jsonify(result)

@app.post("/api/profile")
@require_auth
def update_profile():
    d = request.json or {}
    allowed = {"display_name", "bio", "city", "avatar_url"}
    updates = {k: v for k, v in d.items() if k in allowed}
    if not updates:
        return jsonify({"error": "nothing to update"}), 400
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with get_db() as c:
        c.execute(f"UPDATE users SET {set_clause} WHERE id=?", (*updates.values(), g.user_id))
        user = c.execute(
            "SELECT id,username,display_name,bio,avatar_url,city,points_balance,volunteer_hours,is_senior,is_verified FROM users WHERE id=?",
            (g.user_id,)
        ).fetchone()
    return jsonify(dict(user))

@app.get("/api/my/events")
@require_auth
def my_events():
    with get_db() as c:
        rows = c.execute(
            "SELECT id,title,category,starts_at,participants_count,points_reward,status FROM events WHERE organizer_id=? ORDER BY starts_at DESC LIMIT 20",
            (g.user_id,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/my/points")
@require_auth
def my_points():
    with get_db() as c:
        balance = c.execute("SELECT points_balance FROM users WHERE id=?", (g.user_id,)).fetchone()
        history = c.execute(
            "SELECT delta, reason, created_at FROM point_transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
            (g.user_id,)
        ).fetchall()
    return jsonify({"balance": balance["points_balance"], "history": [dict(r) for r in history]})

@app.get("/api/leaderboard")
def leaderboard():
    city = request.args.get("city","")
    with get_db() as c:
        q = "SELECT id, display_name, city, points_balance, volunteer_hours FROM users WHERE 1=1"
        params = []
        if city:
            q += " AND city LIKE ?"; params.append(f"%{city}%")
        q += " ORDER BY points_balance DESC LIMIT 20"
        rows = c.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows])

# ── NGO Routes ────────────────────────────────────────────────────────────────

@app.get("/api/ngos")
def get_ngos():
    city = request.args.get("city","")
    with get_db() as c:
        q = "SELECT id,username,display_name,bio,city,is_verified FROM users WHERE is_ngo=1"
        params = []
        if city:
            q += " AND city LIKE ?"; params.append(f"%{city}%")
        rows = c.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows])

# ── Feed ──────────────────────────────────────────────────────────────────────

@app.get("/api/feed")
def feed():
    city = request.args.get("city","")
    with get_db() as c:
        # Events
        eq = "SELECT 'event' as type, id, title as content, city, starts_at as created_at, points_reward FROM events WHERE status='active'"
        ep = []
        if city:
            eq += " AND city LIKE ?"; ep.append(f"%{city}%")

        # Good deeds
        dq = "SELECT 'deed' as type, gd.id, gd.description as content, u.city, gd.created_at, 25 as points_reward FROM good_deeds gd JOIN users u ON gd.user_id=u.id"
        dp = []
        if city:
            dq += " WHERE u.city LIKE ?"; dp.append(f"%{city}%")

        events = c.execute(eq + " ORDER BY created_at DESC LIMIT 10", ep).fetchall()
        deeds  = c.execute(dq + " ORDER BY gd.created_at DESC LIMIT 10", dp).fetchall()

    items = [dict(r) for r in events] + [dict(r) for r in deeds]
    items.sort(key=lambda x: x.get("created_at",""), reverse=True)
    return jsonify(items[:20])

# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def platform_stats():
    with get_db() as c:
        users   = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        events  = c.execute("SELECT COUNT(*) FROM events WHERE status='active'").fetchone()[0]
        deeds   = c.execute("SELECT COUNT(*) FROM good_deeds").fetchone()[0]
        visits  = c.execute("SELECT COUNT(*) FROM senior_visits WHERE completed=1").fetchone()[0]
        pts     = c.execute("SELECT SUM(points_balance) FROM users").fetchone()[0] or 0
    return jsonify({
        "users": users, "active_events": events,
        "good_deeds": deeds, "senior_visits_completed": visits,
        "total_points_earned": pts
    })

@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "version": "1.0.0", "platform": "Konnekt",
                    "features": ["sso", "magic_link", "subscriptions", "analytics", "map", "hangouts", "join_queue"]})

# ── Zeitbank (Time / Skill Exchange) ─────────────────────────────────────────

def _init_zeitbank():
    with get_db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS zeitbank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('offer','request')),
            skill TEXT NOT NULL,
            description TEXT DEFAULT '',
            city TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """)
        if c.execute("SELECT COUNT(*) FROM zeitbank").fetchone()[0] == 0:
            _seed_zeitbank(c)

def _seed_zeitbank(c):
    seeds = [
        (2, 'offer',   'Deutsch-Nachhilfe',     'Helfe Kindern & Erwachsenen beim Deutsch lernen — 1h/Woche',   'Bern'),
        (4, 'offer',   'Fahrrad reparieren',     'Flicke Fahrräder aller Art — brauche nur Kaffee als Dank',     'Bern'),
        (7, 'request', 'Einkaufen',              'Brauche jemanden der einmal wöchentlich für mich einkauft',     'Bern'),
        (1, 'offer',   'Yoga-Stunden',           'Biete Outdoor-Yoga im Park — jeden Di 7 Uhr, kostenlos',       'Bern'),
        (10,'offer',   'IT / Computer-Hilfe',    'Helfe Senioren mit Smartphone, PC, Email, WhatsApp',            'Bern'),
        (12,'request', 'Arztbegleitung',         'Brauche Begleitung zum Arzt (einmal im Monat) — Bern',         'Bern'),
        (6, 'offer',   'Gärtnern',               'Biete Hilfe im Garten: säen, jäten, ernten — macht mir Freude','Bern'),
        (5, 'offer',   'Buchhaltung',            'Kleines NGO-Buchhaltung pro bono — 2h/Monat frei',              'Bern'),
        (13,'request', 'Sprachkurs Begleitung',  'Suche jemanden zum Deutsch üben — Conversational Exchange',    'Bern'),
        (8, 'offer',   'Hundesitting',           'Betreue Hunde bis 3 Tage — habe Garten in Bümpliz',            'Bern'),
        (11,'offer',   'Fotografie',             'Biete Fotos für NGOs, Vereine, Events — pro bono',              'Bern'),
        (3, 'request', 'Gesellschaft',           'Freue mich über Besuche zum Tee & Plaudern — jeden Nachmittag','Bern'),
    ]
    for user_id, typ, skill, desc, city in seeds:
        try:
            c.execute("INSERT INTO zeitbank (user_id,type,skill,description,city) VALUES (?,?,?,?,?)",
                      (user_id, typ, skill, desc, city))
        except Exception:
            pass

_init_zeitbank()

@app.get("/api/zeitbank")
def get_zeitbank():
    city = request.args.get("city", "")
    typ  = request.args.get("type", "")
    with get_db() as c:
        q = """SELECT z.*, u.display_name, u.avatar_url, u.volunteer_hours
               FROM zeitbank z JOIN users u ON z.user_id=u.id
               WHERE z.active=1"""
        args = []
        if city:
            q += " AND z.city=?"; args.append(city)
        if typ:
            q += " AND z.type=?"; args.append(typ)
        q += " ORDER BY z.created_at DESC LIMIT 30"
        rows = c.execute(q, args).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/zeitbank")
@require_auth
def add_zeitbank():
    d = request.json or {}
    skill = d.get("skill","").strip()
    typ   = d.get("type","offer")
    if not skill or typ not in ("offer","request"):
        return jsonify({"error": "skill and type required"}), 400
    with get_db() as c:
        c.execute("INSERT INTO zeitbank (user_id,type,skill,description,city) VALUES (?,?,?,?,?)",
                  (g.user_id, typ, skill, d.get("description","").strip(), d.get("city","").strip()))
        new_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return jsonify({"id": new_id}), 201

@app.post("/api/zeitbank/<int:zid>/delete")
@require_auth
def delete_zeitbank(zid):
    with get_db() as c:
        c.execute("UPDATE zeitbank SET active=0 WHERE id=? AND user_id=?", (zid, g.user_id))
    return jsonify({"ok": True})

# ── Monthly Community Challenge ───────────────────────────────────────────────

MONTH_DE = ["Januar","Februar","März","April","Mai","Juni",
            "Juli","August","September","Oktober","November","Dezember"]

@app.get("/api/challenge")
def get_challenge():
    """Return the current monthly community challenge with live progress."""
    now = datetime.utcnow()
    month_name = MONTH_DE[now.month - 1]
    month_label = f"{month_name} {now.year}"
    with get_db() as c:
        deeds  = c.execute("SELECT COUNT(*) FROM good_deeds").fetchone()[0]
        visits = c.execute("SELECT COUNT(*) FROM senior_visits WHERE completed=1").fetchone()[0]
        hours  = c.execute("SELECT SUM(volunteer_hours) FROM users").fetchone()[0] or 0
        events_joined = c.execute("SELECT SUM(participants_count) FROM events").fetchone()[0] or 0
    goal = 500
    return jsonify({
        "month": month_label,
        "title": "Konnekt verbindet",
        "subtitle": f"Gemeinsam {goal} gute Taten bis Ende {month_name}",
        "goal": goal,
        "progress": deeds,
        "milestones": [
            {"at": 100, "label": "100 gute Taten 🌱", "done": deeds >= 100},
            {"at": 250, "label": "250 Verbindungen 💛", "done": deeds >= 250},
            {"at": goal, "label": f"{goal} — die Community leuchtet! ✨", "done": deeds >= goal},
        ],
        "side_stats": {
            "senior_visits": visits,
            "volunteer_hours": hours,
            "events_joined": events_joined,
        }
    })

# ── Referral / Invite system ─────────────────────────────────────────────────

def _init_referrals():
    with get_db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_email TEXT,
            code TEXT UNIQUE NOT NULL,
            used INTEGER DEFAULT 0,
            used_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(referrer_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS waitlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            city TEXT DEFAULT '',
            ref_code TEXT DEFAULT '',
            joined_at TEXT DEFAULT (datetime('now'))
        );
        """)

_init_referrals()

@app.post("/api/invite/generate")
@require_auth
def generate_invite():
    code = secrets.token_urlsafe(8)
    with get_db() as c:
        c.execute("INSERT INTO referrals (referrer_id,code) VALUES (?,?)", (g.user_id, code))
    return jsonify({"code": code, "url": f"/join/{code}"})

@app.get("/api/invite/my")
@require_auth
def my_invites():
    with get_db() as c:
        rows = c.execute("""SELECT r.code, r.used, r.created_at, u.display_name
                            FROM referrals r LEFT JOIN users u ON r.used_by=u.id
                            WHERE r.referrer_id=? ORDER BY r.created_at DESC""", (g.user_id,)).fetchall()
        count = c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND used=1", (g.user_id,)).fetchone()[0]
    return jsonify({"invites": [dict(r) for r in rows], "accepted_count": count})

@app.get("/join/<code>")
def join_via_invite(code):
    """Redirect to app with invite code in URL fragment."""
    with get_db() as c:
        row = c.execute("SELECT id, used FROM referrals WHERE code=?", (code,)).fetchone()
    if not row or row["used"]:
        return _landing_page(notice="Dieser Einladungslink wurde bereits verwendet oder ist ungültig.")
    return _landing_page(invite_code=code)

@app.post("/api/waitlist")
def join_waitlist():
    d = request.json or {}
    email = d.get("email","").strip().lower()
    if not email or "@" not in email:
        return jsonify({"error": "Gültige E-Mail erforderlich"}), 400
    city    = d.get("city","").strip()
    ref_code= d.get("ref_code","").strip()
    with get_db() as c:
        try:
            c.execute("INSERT INTO waitlist (email,city,ref_code) VALUES (?,?,?)", (email, city, ref_code))
        except sqlite3.IntegrityError:
            return jsonify({"ok": True, "already": True})
        count = c.execute("SELECT COUNT(*) FROM waitlist").fetchone()[0]
    return jsonify({"ok": True, "position": count})

@app.get("/api/waitlist/count")
def waitlist_count():
    with get_db() as c:
        n = c.execute("SELECT COUNT(*) FROM waitlist").fetchone()[0]
    return jsonify({"count": n})

# ── Landing page & legal pages ────────────────────────────────────────────────

OWNER_NAME    = "Muharrem Akdemir"
OWNER_EMAIL   = "contract@architect-dna.ch"
OWNER_ADDRESS = "Schaalweg 6, 3053 Münchenbuchsee, Schweiz"
OWNER_UID     = ""                             # leave blank — no company needed for beta

def _landing_page(notice="", invite_code=""):
    with get_db() as c:
        users  = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        deeds  = c.execute("SELECT COUNT(*) FROM good_deeds").fetchone()[0]
        events = c.execute("SELECT COUNT(*) FROM events WHERE status='active'").fetchone()[0]
        wl     = c.execute("SELECT COUNT(*) FROM waitlist").fetchone()[0]
    return render_template_string(LANDING_HTML,
        users=users, deeds=deeds, events=events, waitlist=wl,
        notice=notice, invite_code=invite_code)

LANDING_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0a0f1e">
<meta name="description" content="Konnekt — Ehrenamt, Nachbarschaft und Zusammenhalt. Besser als Instagram, weil es der Welt nützt.">
<meta property="og:title" content="Konnekt — Verbinde dich mit deiner Nachbarschaft">
<meta property="og:description" content="Mach Ehrenamt, besuche Senioren, verdiene Punkte und löse lokale Coupons ein. Kostenlos & beta.">
<meta property="og:image" content="/icons/icon-512.png">
<title>Konnekt — Ehrenamt & Nachbarschaft · v1.0</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;900&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:#05050d;color:#e2e8f0;min-height:100vh}
a{color:inherit;text-decoration:none}

/* hero */
.hero{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:2rem 1.5rem;text-align:center;
  background:radial-gradient(ellipse 80% 60% at 50% 0%,#1e1b4b,transparent),
             radial-gradient(ellipse 60% 40% at 80% 100%,#06b6d410,transparent)}
.beta-badge{display:inline-flex;align-items:center;gap:.4rem;background:rgba(139,92,246,.15);
  border:1px solid rgba(139,92,246,.35);border-radius:99px;padding:.3rem 1rem;
  font-size:.75rem;font-weight:700;color:#a78bfa;letter-spacing:.05em;margin-bottom:1.5rem}
.hero-emoji{font-size:3.5rem;margin-bottom:.75rem}
h1{font-size:clamp(2rem,6vw,3.5rem);font-weight:900;letter-spacing:-.03em;
   background:linear-gradient(135deg,#a78bfa,#60a5fa,#34d399);
   -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:.75rem}
.hero-sub{font-size:clamp(.95rem,2.5vw,1.15rem);color:#94a3b8;max-width:520px;line-height:1.6;margin-bottom:2rem}

/* stats */
.stats{display:flex;gap:1.5rem;justify-content:center;flex-wrap:wrap;margin-bottom:2.5rem}
.stat{text-align:center}
.stat-num{font-size:1.8rem;font-weight:900;color:#a78bfa}
.stat-lbl{font-size:.72rem;color:#64748b;text-transform:uppercase;letter-spacing:.06em}

/* CTA */
.cta-group{display:flex;flex-direction:column;gap:.75rem;align-items:center;width:100%;max-width:360px}
.btn-main{display:block;width:100%;background:linear-gradient(135deg,#7c3aed,#3b82f6);color:white;
  border:none;border-radius:14px;padding:1rem;font-size:1rem;font-weight:800;
  cursor:pointer;font-family:inherit;box-shadow:0 8px 30px rgba(124,58,237,.35);transition:transform .15s}
.btn-main:active{transform:scale(.97)}
.btn-app{display:block;width:100%;background:#0f0f23;color:#94a3b8;border:1px solid #1c1c38;
  border-radius:14px;padding:.85rem;font-size:.9rem;font-weight:600;
  cursor:pointer;font-family:inherit;transition:border-color .2s}
.btn-app:hover{border-color:#7c3aed}
.btn-app span{font-size:.75rem;display:block;color:#475569;margin-top:.1rem}

/* waitlist form */
.waitlist-form{display:flex;flex-direction:column;gap:.6rem;width:100%;max-width:360px;margin-top:.5rem}
.wl-input{background:#0c0c18;border:1px solid #1c1c38;border-radius:10px;
  padding:.75rem 1rem;color:#e2e8f0;font-size:.92rem;font-family:inherit;outline:none;
  transition:border-color .2s}
.wl-input:focus{border-color:#7c3aed}
.wl-success{background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.3);
  border-radius:10px;padding:.75rem 1rem;font-size:.85rem;color:#34d399;display:none;text-align:center}
.notice{background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.3);
  border-radius:10px;padding:.65rem 1rem;font-size:.82rem;color:#fbbf24;margin-bottom:1rem;max-width:420px}

/* features */
.features{padding:4rem 1.5rem;max-width:900px;margin:0 auto}
.features h2{font-size:1.5rem;font-weight:800;text-align:center;margin-bottom:.5rem}
.features-sub{text-align:center;color:#64748b;font-size:.88rem;margin-bottom:2.5rem}
.feat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:1rem}
.feat-card{background:#0c0c18;border:1px solid #1c1c38;border-radius:16px;padding:1.25rem;
  position:relative;overflow:hidden}
.feat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--c)}
.feat-icon{font-size:1.75rem;margin-bottom:.6rem}
.feat-title{font-weight:700;font-size:.95rem;margin-bottom:.3rem}
.feat-desc{font-size:.78rem;color:#64748b;line-height:1.5}

/* how it works */
.how{background:#080815;padding:3rem 1.5rem;text-align:center}
.how h2{font-size:1.4rem;font-weight:800;margin-bottom:2rem}
.steps{display:flex;gap:1.5rem;justify-content:center;flex-wrap:wrap;max-width:700px;margin:0 auto}
.step{flex:1;min-width:160px}
.step-num{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#3b82f6);
  color:white;font-weight:800;display:flex;align-items:center;justify-content:center;
  margin:0 auto .75rem}
.step-title{font-weight:700;font-size:.88rem;margin-bottom:.3rem}
.step-desc{font-size:.75rem;color:#64748b;line-height:1.4}

/* footer */
.site-footer{border-top:1px solid #0f0f23;padding:1.5rem;text-align:center;font-size:.73rem;color:#334155}
.site-footer a{color:#475569;margin:0 .5rem}
.site-footer a:hover{color:#a78bfa}
</style>
</head>
<body>

<div class="hero">
  {% if notice %}
  <div class="notice">⚠️ {{ notice }}</div>
  {% endif %}

  <div class="beta-badge">✦ v1.0 · Jetzt live · Handgebaut in Bern</div>
  <div class="hero-emoji">🌐</div>
  <h1>Konnekt</h1>
  <p class="hero-sub">
    Ehrenamt. Nachbarschaft. Zusammenhalt.<br>
    Verdiene Punkte für gute Taten — löse sie bei lokalen Geschäften ein.
    Kein Algorithmus. Keine Werbung. Einfach echte Menschen.
  </p>

  <div class="stats">
    <div class="stat"><div class="stat-num">{{ users }}</div><div class="stat-lbl">Mitglieder</div></div>
    <div class="stat"><div class="stat-num">{{ deeds }}</div><div class="stat-lbl">Gute Taten</div></div>
    <div class="stat"><div class="stat-num">{{ events }}</div><div class="stat-lbl">Events</div></div>
    <div class="stat"><div class="stat-num">{{ waitlist }}</div><div class="stat-lbl">auf Warteliste</div></div>
  </div>

  <div class="cta-group">
    <button class="btn-main" onclick="window.location='/'">
      🚀 Jetzt ausprobieren — kostenlos
    </button>
    <button class="btn-app" onclick="showWaitlist()">
      📩 Beta-Zugang per E-Mail
      <span>Erhalte Benachrichtigungen & Updates</span>
    </button>
  </div>

  <div class="waitlist-form" id="wl-form" style="display:none">
    <input class="wl-input" id="wl-email" type="email" placeholder="deine@email.com">
    <input class="wl-input" id="wl-city" type="text" placeholder="Stadt (z.B. Bern)">
    <button class="btn-main" onclick="submitWaitlist()" style="padding:.8rem">Eintragen</button>
    <div class="wl-success" id="wl-success"></div>
  </div>
</div>

<div class="features">
  <h2>Was ist Konnekt?</h2>
  <p class="features-sub">Eine Plattform die Menschen verbindet — nicht Follower zählt</p>
  <div class="feat-grid">
    <div class="feat-card" style="--c:#10b981">
      <div class="feat-icon">🌱</div>
      <div class="feat-title">VolunteerHub</div>
      <div class="feat-desc">Melde dich für Ehrenamt-Events an und verdiene Punkte. Stadtputz, Seniorenbegleitung, Blutspende — alles in deiner Umgebung.</div>
    </div>
    <div class="feat-card" style="--c:#ec4899">
      <div class="feat-icon">💛</div>
      <div class="feat-title">Nahbar</div>
      <div class="feat-desc">Kein Nachbar bleibt allein. Besuche Senioren, verbinde dich mit Nachbarn, trage gute Taten ein — jede Verbindung bringt Punkte.</div>
    </div>
    <div class="feat-card" style="--c:#f59e0b">
      <div class="feat-icon">🎟️</div>
      <div class="feat-title">Coupons & Belohnungen</div>
      <div class="feat-desc">Deine Punkte sind real — einlösbar bei lokalen Bäckereien, Kinos, Sportcentern. Ehrenamt wird sichtbar belohnt.</div>
    </div>
    <div class="feat-card" style="--c:#00ff88">
      <div class="feat-icon">⏱️</div>
      <div class="feat-title">Zeitbank</div>
      <div class="feat-desc">Tausche Fähigkeiten ohne Geld. Ich biete Deutsch-Nachhilfe — du bringst mir Yoga bei. Eine Stunde = eine Stunde.</div>
    </div>
    <div class="feat-card" style="--c:#8b5cf6">
      <div class="feat-icon">📲</div>
      <div class="feat-title">PWA — kein App Store</div>
      <div class="feat-desc">Installiere Konnekt direkt im Browser. Kein Download nötig. Funktioniert auf Android & iPhone genau wie eine App.</div>
    </div>
    <div class="feat-card" style="--c:#3b82f6">
      <div class="feat-icon">🔒</div>
      <div class="feat-title">Keine Werbung. Nie.</div>
      <div class="feat-desc">Kein Algorithmus der dich süchtig hält. Keine verkauften Daten. Konnekt finanziert sich durch NGO-Accounts und Community-Partnerschaften.</div>
    </div>
    <div class="feat-card" style="--c:#8b5cf6">
      <div class="feat-icon">🎮</div>
      <div class="feat-title">Hangouts &amp; Spontan-Events</div>
      <div class="feat-desc">UNO im Park, Sprachcafé, Brettspiele — sieh offene Hangouts auf der Karte und frag einfach ob du mitmachen kannst. Offen für alle.</div>
    </div>
  </div>
</div>

<div class="how">
  <h2>So funktioniert's</h2>
  <div class="steps">
    <div class="step">
      <div class="step-num">1</div>
      <div class="step-title">Registrieren</div>
      <div class="step-desc">Kostenlos, keine App nötig — einfach im Browser öffnen</div>
    </div>
    <div class="step">
      <div class="step-num">2</div>
      <div class="step-title">Mitmachen</div>
      <div class="step-desc">Events besuchen, Senioren begleiten, gute Taten eintragen</div>
    </div>
    <div class="step">
      <div class="step-num">3</div>
      <div class="step-title">Punkte sammeln</div>
      <div class="step-desc">Jede gute Tat = Punkte. Automatisch, transparent</div>
    </div>
    <div class="step">
      <div class="step-num">4</div>
      <div class="step-title">Einlösen</div>
      <div class="step-desc">Gratis Kaffee, Kinokarte, Fitness — bei lokalen Partnern</div>
    </div>
  </div>
</div>

<!-- Personal note from the founder -->
<div style="background:#07071a;border-top:1px solid #1c1c38;padding:3rem 1.5rem">
  <div style="max-width:600px;margin:0 auto">
    <div style="font-size:1.1rem;font-weight:800;margin-bottom:1rem;color:#e2e8f0">Eine persönliche Note 👋</div>
    <p style="font-size:.9rem;color:#94a3b8;line-height:1.75;margin-bottom:1rem">
      Ich bin Muharrem. Ich hab Konnekt gebaut weil ich glaube, dass Technologie Menschen zusammenbringen
      sollte — nicht auseinander. Nicht durch Algorithmen die dich süchtig halten, sondern durch echte
      Aktionen in der echten Welt.
    </p>
    <p style="font-size:.9rem;color:#94a3b8;line-height:1.75;margin-bottom:1rem">
      Das hier ist <strong style="color:#a78bfa">Version 1.0</strong> — live, wachsend, und mit Herz gebaut.
      Manches ist noch roh. Manches wird noch besser. Ich baue das nicht für Investoren oder
      Exit-Strategie — ich bau es weil ich in Bern wohne und mir wünsche, dass wir uns mehr kennen.
    </p>
    <p style="font-size:.9rem;color:#94a3b8;line-height:1.75;margin-bottom:1.5rem">
      Wenn du eine NGO vertrittst, einen Verein leitest, oder einfach Feedback hast —
      schreib mir direkt. Kein Ticketsystem, kein Chatbot.
    </p>
    <a href="mailto:contract@architect-dna.ch" style="display:inline-flex;align-items:center;gap:.5rem;background:rgba(139,92,246,.15);border:1px solid rgba(139,92,246,.35);border-radius:10px;padding:.65rem 1.2rem;font-size:.85rem;font-weight:700;color:#a78bfa;text-decoration:none">
      ✉️ contract@architect-dna.ch
    </a>
    <div style="margin-top:1.5rem;font-size:.78rem;color:#334155">
      Built with care · Bern, Schweiz · 2026
    </div>
  </div>
</div>

<div class="site-footer">
  <div style="margin-bottom:.5rem">
    <a href="/impressum">Impressum</a>
    <a href="/datenschutz">Datenschutz</a>
    <a href="/">App öffnen</a>
  </div>
  <div>© 2026 Konnekt · v1.0 · Mit ❤️ für Bern und die Welt</div>
</div>

<script>
function showWaitlist() {
  document.getElementById('wl-form').style.display='flex';
  document.getElementById('wl-email').focus();
}
async function submitWaitlist() {
  const email = document.getElementById('wl-email').value.trim();
  const city  = document.getElementById('wl-city').value.trim();
  const code  = new URLSearchParams(location.search).get('ref') || '';
  if (!email) return;
  const r = await fetch('/api/waitlist', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({email, city, ref_code:code})
  });
  const d = await r.json();
  const el = document.getElementById('wl-success');
  el.style.display='block';
  el.textContent = d.already
    ? '✓ Du bist bereits dabei!'
    : `✓ Du bist #${d.position} auf der Liste — danke! Wir melden uns.`;
}
// Auto-open waitlist if invite code present
const params = new URLSearchParams(location.search);
if (params.get('ref')) showWaitlist();
</script>
</body>
</html>"""

IMPRESSUM_HTML = """<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><title>Impressum · Konnekt</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;background:#05050d;color:#e2e8f0;max-width:680px;margin:0 auto;padding:2rem 1.5rem}
h1{font-size:1.4rem;font-weight:800;margin-bottom:1.5rem;color:#a78bfa}
h2{font-size:1rem;font-weight:700;margin:1.5rem 0 .5rem}
p,address{font-size:.88rem;color:#94a3b8;line-height:1.7;font-style:normal}
a{color:#60a5fa}
.back{display:inline-block;margin-bottom:1.5rem;font-size:.82rem;color:#475569}
.info-box{background:rgba(167,139,250,.08);border:1px solid rgba(167,139,250,.25);border-radius:10px;padding:1rem 1.2rem;margin:.75rem 0}
.req-form{display:flex;flex-direction:column;gap:.6rem;margin-top:.75rem}
.req-form input,.req-form textarea,.req-form select{background:#0c0c1a;border:1px solid #1c1c38;border-radius:8px;padding:.65rem .9rem;color:#e2e8f0;font-size:.88rem;font-family:inherit;outline:none}
.req-form textarea{min-height:80px;resize:vertical}
.req-btn{background:linear-gradient(135deg,#7c3aed,#3b82f6);color:white;border:none;border-radius:8px;padding:.75rem;font-size:.88rem;font-weight:700;cursor:pointer;font-family:inherit}
.success-msg{background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.3);border-radius:8px;padding:.75rem;color:#34d399;font-size:.85rem;display:none}
</style></head>
<body>
<a class="back" href="/landing">← Zurück</a>
<h1>Impressum</h1>

<h2>Angaben gemäß § 5 TMG / Art. 3 lit. s UWG (Schweiz: Art. 3 UWG)</h2>
<div class="info-box">
<address>
<strong>""" + OWNER_NAME + """</strong><br>
E-Mail: <a href="mailto:""" + OWNER_EMAIL + """">""" + OWNER_EMAIL + """</a><br>
Plattform: Konnekt (Beta) · Betrieb als Privatperson
</address>
</div>

<h2>Physische Adresse</h2>
<p>Die physische Postadresse des Betreibers wird gemäß Schweizer Datenschutzgesetz (DSG Art. 19)
zum Schutz der Privatsphäre nicht öffentlich angezeigt. Sie wird auf begründete, verifizierte
Anfrage von Behörden, Gerichten oder berechtigten Dritten mitgeteilt.</p>

<div class="info-box">
<strong>Adresse anfordern (Behörden / Rechtliches)</strong>
<p style="margin:.5rem 0 .75rem;font-size:.82rem">Für rechtliche Anfragen, Behördenanfragen oder bei berechtigtem Interesse
füllen Sie das folgende Formular aus. Wir antworten innerhalb von 14 Tagen.</p>
<form class="req-form" onsubmit="submitRequest(event)">
  <input type="text" id="req-name" placeholder="Ihr Name / Organisation *" required>
  <input type="text" id="req-org" placeholder="Behörde / Firma (falls zutreffend)">
  <input type="email" id="req-email" placeholder="Ihre E-Mail-Adresse *" required>
  <select id="req-purpose" required>
    <option value="">Anfrage-Zweck wählen *</option>
    <option value="legal">Rechtliche Angelegenheit</option>
    <option value="authority">Behördenanfrage</option>
    <option value="court">Gerichtsverfahren</option>
    <option value="press">Presseanfrage</option>
    <option value="other">Sonstiges</option>
  </select>
  <textarea id="req-desc" placeholder="Kurze Beschreibung des Anliegens *" required></textarea>
  <button class="req-btn" type="submit">Anfrage einreichen</button>
</form>
<div class="success-msg" id="req-success">✓ Anfrage eingegangen. Sie erhalten eine Antwort innerhalb von 14 Tagen.</div>
</div>

<h2>Verantwortlich für den Inhalt</h2>
<p>""" + OWNER_NAME + """ (Privatperson / Einzelunternehmen, Beta-Phase)</p>

<h2>Haftungsausschluss</h2>
<p>Konnekt befindet sich im Beta-Stadium. Inhalte werden von Nutzern erstellt.
Der Betreiber übernimmt keine Haftung für Richtigkeit oder Vollständigkeit
von Nutzerinhalten. Bei Verstössen bitte an <a href="mailto:""" + OWNER_EMAIL + """">""" + OWNER_EMAIL + """</a> wenden.</p>

<h2>Streitschlichtung</h2>
<p>Der Betreiber nimmt nicht an Verbraucher-Streitbeilegungsverfahren teil.
Für Schweizer Nutzer gilt das DSG; für EU-Nutzer die DSGVO.</p>

<script>
async function submitRequest(e) {
  e.preventDefault();
  const btn = e.target.querySelector('button');
  btn.disabled = true; btn.textContent = 'Wird gesendet…';
  try {
    const r = await fetch('/api/legal/address-request', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        name: document.getElementById('req-name').value,
        org: document.getElementById('req-org').value,
        email: document.getElementById('req-email').value,
        purpose: document.getElementById('req-purpose').value + ': ' + document.getElementById('req-desc').value
      })
    });
    if (r.ok) {
      document.querySelector('.req-form').style.display = 'none';
      document.getElementById('req-success').style.display = 'block';
    } else {
      btn.disabled = false; btn.textContent = 'Anfrage einreichen';
    }
  } catch { btn.disabled = false; btn.textContent = 'Anfrage einreichen'; }
}
</script>
</body></html>"""

DATENSCHUTZ_HTML = """<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><title>Datenschutz · Konnekt</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;background:#05050d;color:#e2e8f0;max-width:680px;margin:0 auto;padding:2rem 1.5rem}
h1{font-size:1.4rem;font-weight:800;margin-bottom:1.5rem;color:#a78bfa}
h2{font-size:1rem;font-weight:700;margin:1.5rem 0 .5rem}
p,li{font-size:.88rem;color:#94a3b8;line-height:1.7}
ul{padding-left:1.2rem}
a{color:#60a5fa}
.back{display:inline-block;margin-bottom:1.5rem;font-size:.82rem;color:#475569}
</style></head>
<body>
<a class="back" href="/landing">← Zurück</a>
<h1>Datenschutzerklärung</h1>
<p>Stand: April 2026 · Gültig für die Beta-Version von Konnekt</p>

<h2>1. Verantwortlicher</h2>
<p>""" + OWNER_NAME + """ · Kontakt: <a href="mailto:""" + OWNER_EMAIL + """">""" + OWNER_EMAIL + """</a><br>
Physische Adresse auf Anfrage verfügbar (siehe <a href="/impressum">Impressum</a>).</p>

<h2>2. Welche Daten wir erheben</h2>
<ul>
<li><strong>Registrierungsdaten:</strong> E-Mail-Adresse, Benutzername, Stadt</li>
<li><strong>Profilangaben:</strong> Anzeigename, Bio (freiwillig)</li>
<li><strong>Aktivitätsdaten:</strong> Events, gute Taten, Punkte-Transaktionen</li>
<li><strong>Technische Daten:</strong> IP-Adresse (Server-Logs, 7 Tage Aufbewahrung)</li>
</ul>

<h2>3. Rechtsgrundlage (DSGVO / DSG)</h2>
<p>Verarbeitung auf Basis von Art. 6 Abs. 1 lit. b DSGVO (Vertragserfüllung)
und Art. 6 Abs. 1 lit. a DSGVO (Einwilligung bei freiwilligen Angaben).
Schweizer Nutzer: Bearbeitung nach Art. 31 DSG.</p>

<h2>4. Weitergabe an Dritte</h2>
<p>Keine Weitergabe an Dritte zu Werbe- oder Analysezwecken.
Avatarbilder werden von <strong>pravatar.cc</strong> geladen (externer Dienst, datenschutzfreundlich).
Event-Bilder von <strong>picsum.photos</strong> (Unsplash-basiert, keine Personendaten).</p>

<h2>5. Datenspeicherung & Sicherheit</h2>
<p>Daten werden in einer SQLite-Datenbank auf dem Server gespeichert.
Passwörter werden gehasht (SHA-256 + Salt). Verbindungen über HTTPS verschlüsselt.
Beta-Phase: kein kommerzielles Hosting-SLA.</p>

<h2>6. Aufbewahrungsdauer</h2>
<p>Kontodaten: bis zur Löschung durch den Nutzer oder 2 Jahre Inaktivität.
Server-Logs: 7 Tage. Waitlist-E-Mails: bis zu 6 Monate nach Beta-Ende.</p>

<h2>7. Deine Rechte</h2>
<ul>
<li>Auskunft über gespeicherte Daten (Art. 15 DSGVO)</li>
<li>Berichtigung unrichtiger Daten (Art. 16 DSGVO)</li>
<li>Löschung / „Recht auf Vergessenwerden" (Art. 17 DSGVO)</li>
<li>Datenportabilität (Art. 20 DSGVO)</li>
</ul>
<p>Anfragen an: <a href="mailto:""" + OWNER_EMAIL + """">""" + OWNER_EMAIL + """</a> — Antwort innerhalb von 30 Tagen.</p>

<h2>8. Keine Cookies, kein Tracking</h2>
<p>Konnekt verwendet keine Tracking-Cookies und kein Analytics-Tool von Drittanbietern.
LocalStorage wird ausschliesslich für Session-Token und Theme-Einstellungen verwendet.</p>

<h2>9. Minderjährige</h2>
<p>Konnekt richtet sich nicht an Kinder unter 16 Jahren.
Nutzer unter 16 Jahren benötigen die Zustimmung einer erziehungsberechtigten Person.</p>

<h2>10. Änderungen dieser Erklärung</h2>
<p>Änderungen werden auf dieser Seite veröffentlicht.
Bei wesentlichen Änderungen informieren wir registrierte Nutzer per E-Mail.</p>
</body></html>"""

@app.get("/landing")
def landing():
    return _landing_page()

@app.get("/impressum")
def impressum():
    return IMPRESSUM_HTML

@app.get("/datenschutz")
def datenschutz():
    return DATENSCHUTZ_HTML

# ── QR code endpoint ──────────────────────────────────────────────────────────

@app.get("/api/qr")
def qr_redirect_info():
    """Returns the URL that should be on QR stickers."""
    base = request.host_url.rstrip('/')
    return jsonify({
        "app_url": base + "/",
        "landing_url": base + "/landing",
        "qr_target": base + "/landing",
        "instructions": "Print QR pointing to /landing — it shows stats + install button"
    })

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)
