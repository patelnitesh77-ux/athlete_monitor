# Athlete Monitor — Pilot

Multidisciplinary athlete monitoring for a wrestling + archery camp (15–20 athletes, 6–7 staff).
Streamlit frontend · Supabase Postgres backend · free tiers only.

**Roles**

| Role | Access | How they get in |
|---|---|---|
| Athlete | Own daily wellness form (+ arrow count for archers) | Private link `?token=...` — no login |
| Coach / S&C | Log field sRPE, gym set/rep/weight, arrows; dashboard; sees availability + physio restrictions **only** | Username + password |
| Physio | Full medical: pain queue, injuries, rehab phases, rehab sessions, availability | Username + password |
| Admin (you) | Everything + athlete links + password resets | Username + password |

**Metrics**: daily load = Σ sRPE across field+gym+rehab · ACWR (7d/28d rolling means, "building…" until 28 days) · monotony & strain · wellness z-scores vs own 21-day baseline (absolute thresholds first 14 days) · wrestler 48h weight-drop alert · weekly arrows.

---

## Setup (one-time, ~20 minutes)

### 1. Supabase (database)
1. Create a free project at supabase.com → note the **connection string** (Project Settings → Database → Connection string → URI). Use the *session pooler* URI.
2. SQL Editor → New query → paste all of `schema.sql` → Run.
3. Default staff logins created: `yogi` (admin), `coach1`, `physio1` — all with password `changeme123`. **Change these via Admin → Staff passwords immediately after first login.**

### 2. Seed demo data (recommended)
```bash
# preview without touching the DB:
python seed_data.py --dry-run          # writes CSVs to seed_preview/

# write 4 demo athletes x 5 weeks to Supabase:
DATABASE_URL="postgres://..." python seed_data.py
```
Demo scenarios: steady wrestler (green) · wrestler in a load-spike + weight cut (red ACWR + weight flags) · archer with a wellness dip (red z-flags) · archer with an open shoulder injury in Reconditioning (rehab loads, Modified availability). Delete demo athletes from the athletes table when the pilot goes live.

### 3. Streamlit Community Cloud (hosting)
1. Push this folder to a **private** GitHub repo.
2. share.streamlit.io → New app → pick the repo, main file `app.py`.
3. App → Settings → Secrets → add:
   ```toml
   DATABASE_URL = "postgres://...your supabase URI..."
   ```
4. Deploy. Note your app URL (e.g. `https://yourapp.streamlit.app`).

### 4. Athlete links
Admin panel → Athletes & links → add each athlete → paste your app URL → copy each private link and send it by individual WhatsApp DM (not the group — the token *is* their identity).

---

## Verification checklist (run once after deploy)

**Athlete link (open on a phone)**
- [ ] Link opens straight to the form, no login
- [ ] Wrestler sees body-weight field; archer sees arrow count instead
- [ ] Pain toggle reveals location/type/days; submitting without location is blocked
- [ ] Resubmitting the same day updates rather than duplicates

**Coach login**
- [ ] Field session save shows computed AU load
- [ ] Gym logger pre-fills from last session; tonnage shown on save
- [ ] Athlete picker shows availability badge + restrictions banner
- [ ] Dashboard → injured athlete → "Injury / rehab" tab shows ONLY status + restrictions (no diagnosis, no phases)

**Physio login**
- [ ] Pain queue lists the demo archer's shoulder report on its day
- [ ] Creating an injury auto-starts Acute phase; phases advance; closing sets Full RTP
- [ ] Rehab session with "count in load" ticked appears in the athlete's daily load
- [ ] Availability update is instantly visible in coach view

**Admin login**
- [ ] Dashboard compliance panel lists missing athletes + WhatsApp nudge text
- [ ] Squad grid sorts red → amber → green; spike-cut wrestler is red with ACWR + weight reasons
- [ ] New athletes show "building…" ACWR (no false flags)
- [ ] Password reset works

## Known limitations (pilot)
- Streamlit Cloud sleeps when idle → first morning load takes ~30–60 s.
- Coach/physio separation is enforced in app code, not database RLS (v2 item).
- Anyone with an athlete's link can submit as them — treat links like passwords.
- No push notifications; the morning nudge list is copy-paste.

## v2 (scale-up) path
Schema and metrics carry over unchanged: keep Supabase, add Row-Level Security, rebuild the frontend in React (mobile PWA for athletes), add WhatsApp/API nudges.
