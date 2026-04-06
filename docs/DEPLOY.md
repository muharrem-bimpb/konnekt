# Konnekt — Deployment Guide

## Local dev (current)
```bash
cd ~/konnekt/api
pip install -r requirements.txt
python app.py
# → http://localhost:8529
```

## Production VPS (€5/month Hetzner CX22)
```bash
# 1. Server setup (Ubuntu 22.04)
apt update && apt install -y python3-pip nginx certbot python3-certbot-nginx git

# 2. Clone
git clone https://github.com/yourname/konnekt /opt/konnekt
cd /opt/konnekt/api && pip install -r requirements.txt

# 3. Systemd service
cat > /etc/systemd/system/konnekt.service << EOF
[Unit]
Description=Konnekt API
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/konnekt/api
ExecStart=/usr/local/bin/gunicorn -w 4 -b 127.0.0.1:8529 app:app
Restart=always
Environment=SECRET_KEY=your-production-secret
Environment=DB_PATH=/opt/konnekt/data/konnekt.db

[Install]
WantedBy=multi-user.target
EOF
systemctl enable --now konnekt

# 4. Nginx reverse proxy
cat > /etc/nginx/sites-available/konnekt << EOF
server {
    listen 80;
    server_name konnekt.app www.konnekt.app;

    location / {
        proxy_pass http://127.0.0.1:8529;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF
ln -s /etc/nginx/sites-available/konnekt /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx

# 5. SSL (free Let's Encrypt)
certbot --nginx -d konnekt.app -d www.konnekt.app
```

## App Store (iOS) — Capacitor
```bash
# In frontend/ directory:
npm init -y
npm install @capacitor/core @capacitor/cli @capacitor/ios

npx cap init Konnekt com.konnekt.app --web-dir public
npx cap add ios
npx cap copy ios

# Open Xcode, set bundle ID, signing, submit
npx cap open ios
```
Requirements: macOS + Xcode + Apple Developer ($99/year)

## Google Play — Capacitor
```bash
npx cap add android
npx cap copy android
npx cap open android
# Build signed APK in Android Studio → Upload to Play Console
```
Requirements: Google Play Developer ($25 one-time)

## Database migration (SQLite → PostgreSQL for scale)
```bash
pip install sqlalchemy psycopg2
# Replace sqlite3 calls with SQLAlchemy (30min refactor)
# All SQL is standard — no SQLite-specific syntax used
```

## Environment variables (production .env)
```
HOST=0.0.0.0
PORT=8529
DB_PATH=/opt/konnekt/data/konnekt.db
SECRET_KEY=<secrets.token_hex(32)>
FCM_SERVER_KEY=<Firebase key for push notifications>
S3_BUCKET=<for file uploads>
S3_ACCESS_KEY=<>
S3_SECRET_KEY=<>
```

## Scaling path
- 0–1k users: Single VPS, SQLite, no changes needed
- 1k–10k: Add PostgreSQL, Redis for sessions, second Gunicorn worker
- 10k–100k: Docker + load balancer, CDN for static files
- 100k+: Kubernetes, read replicas, dedicated media server
