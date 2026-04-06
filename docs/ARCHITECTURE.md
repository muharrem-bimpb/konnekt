# Konnekt — Platform Architecture

## What it is
A social impact platform with two pillars:
1. **VolunteerHub** — find, organize, reward volunteer events with redeemable coupons
2. **Nahbar** — anti-loneliness network: neighbor connections, senior program, context-based activity suggestions

## Why it wins over Instagram
- Reward loop tied to real-world positive action (not engagement bait)
- NGOs get a free organizing tool → they bring their communities
- Municipalities pay for loneliness prevention → sustainable revenue without selling user data
- Local businesses pay for coupon redemptions → drives foot traffic
- No ads, no algorithm manipulation, no infinite scroll

---

## Tech Stack (Deploy-Ready)

### Backend
- **Language:** Python / FastAPI (production) or Flask (MVP — what's built here)
- **DB:** SQLite (MVP) → PostgreSQL (production, trivial migration with SQLAlchemy)
- **Auth:** JWT tokens + refresh tokens
- **Push Notifications:** Firebase Cloud Messaging (FCM)
- **File Storage:** Local (MVP) → S3-compatible (production)
- **Maps/Geo:** OpenStreetMap + Nominatim (no API costs)

### Frontend / Mobile
- **PWA first** — works on any browser, installable on iOS (Add to Home Screen) + Android
- **Capacitor.js** — wraps the PWA into a native iOS/Android app for App Store submission
- **Single codebase:** HTML/CSS/JS (no framework dependency)

### Deployment
- **MVP:** Single VPS (€5/month Hetzner/DigitalOcean), Nginx reverse proxy, Gunicorn
- **Scale:** Docker + docker-compose → Kubernetes when needed
- **CI/CD:** GitHub Actions → auto-deploy on push
- **SSL:** Let's Encrypt (certbot, free)

---

## App Store Path (Capacitor)
```bash
npm install @capacitor/core @capacitor/cli @capacitor/ios @capacitor/android
npx cap init Konnekt com.konnekt.app
npx cap add ios
npx cap add android
npx cap copy
npx cap open ios     # opens Xcode → submit to App Store
npx cap open android # opens Android Studio → submit to Play Store
```
Requirements: Apple Developer Account ($99/yr), Google Play ($25 once)

---

## Revenue Model
| Source | Mechanism | Realistic MRR at 1k users |
|---|---|---|
| NGO Pro accounts | €49/month per organization | €490+ |
| Municipality contracts | Annual license for city loneliness program | €2k–20k/year |
| Business coupon program | €0.50–1.00 per coupon redemption | Variable |
| EU/national grants | Social innovation, digital inclusion | €10k–100k one-time |
| Foundation grants | Robert Bosch, Bertelsmann, etc. | Project-based |

**No user data selling. No ads.**

---

## Database Schema

### Users
- id, username, email, password_hash, avatar_url
- city, lat, lng (for proximity matching)
- points_balance, coupons_earned, volunteer_hours
- is_senior (boolean), needs_visitor (boolean)
- created_at

### Events (VolunteerHub)
- id, organizer_id, title, description, category
- location, lat, lng, address
- starts_at, ends_at, max_participants
- points_reward, status
- tags (JSON)

### Event Registrations
- event_id, user_id, status, points_awarded, created_at

### Coupons
- id, business_id, title, description, points_cost
- valid_until, max_redemptions, redemptions_count
- category (food/transport/culture/sport)

### Coupon Redemptions
- coupon_id, user_id, redeemed_at, qr_code

### Neighbor Connections (Nahbar)
- id, user_a, user_b, status, created_at
- connection_type (friend/visitor/emergency_contact)

### Senior Visits
- id, senior_id, visitor_id, scheduled_at, completed, note

### Activity Suggestions
- id, user_id, suggestion_text, category, lat, lng
- accepted (bool), points_awarded

### NGO Organizations
- id, name, description, verified, contact_email
- city, website, tags

---

## Key Differentiators vs Instagram
1. Points = real currency (coupons at real businesses)
2. Feed = local events + neighbor connections, NOT algorithmic dopamine
3. Privacy: no behavioral profiling, no ad targeting
4. Senior program: opt-in, city-verified, safeguarded
5. NGO backbone: organizations bring existing communities
6. Offline-capable PWA: works in areas with poor connectivity
