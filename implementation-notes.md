# Implementation Notes

## Goal
Streamlit pilot of a multidisciplinary athlete monitoring system (wrestling + archery, 15–20 athletes, 6–7 staff) backed by Supabase Postgres: athlete wellness via private token links, coach load logging (sRPE + gym set/rep/weight + arrows), physio injury/rehab/RTP module with privacy separation, and a flag-driven dashboard whose landing view is wellness-form compliance.

## Approved Plan Summary
2-then-3 strategy: Streamlit now on Streamlit Community Cloud, Supabase Postgres as the DB so the eventual React rebuild keeps schema + data. Data model, access model, metrics engine (ACWR, monotony, strain, z-scores, cold-start handling), dashboard flow, and arrow-conflict rule approved as per plan message.

## Known Knowns
- Roles: athlete (token link, own wellness + arrows only), coach (loads, all athletes, availability + restrictions only from medical), physio (full medical), admin = Yogi (everything).
- Wellness form: sleep quality, sleep hours, fatigue, soreness, stress, mood, hydration, body weight (wrestlers), pain check → location/type/days.
- Flags: red = z ≤ −1.5, new pain, ACWR > 1.5, wrestler wt −2%/48h; amber = ACWR 1.3–1.5 or < 0.8, missed form, z ≤ −1.0.
- Daily load = sum of field + gym + rehab session loads (prevents rehab double-counting).

## Known Unknowns
- Real Supabase credentials/deployment — user runs schema.sql and sets secrets.
- Actual mobile feel of the Streamlit form on athletes' phones.

## Unknown Knowns Surfaced
- Morning-first view is compliance, not the grid.
- Coaches must NOT see injury detail — only availability + restrictions text.

## Unknown Unknowns Discovered
- (during build) `st.experimental_get_query_params` deprecated → used `st.query_params`.
- Postgres `numeric` returns Decimal via psycopg2 → cast to float in db layer before pandas math.

## Decisions Made
| Decision | Reason | Risk | Reversible? |
|---|---|---|---|
| Manual routing in app.py instead of Streamlit multipage | Role/token gating is airtight in one router | Low | Yes |
| pbkdf2_hmac (stdlib) for staff passwords | No bcrypt offline; stdlib is adequate for pilot | Low | Yes |
| Metrics in pure pandas/numpy, no streamlit import | Unit-testable offline; reusable in v2 React backend | None | Yes |
| ACWR = 7d mean ÷ 28d mean of daily load, "insufficient" < 28 days of history | Standard rolling-average method; cold-start honesty | Low | Yes |
| Z-flags use absolute thresholds (item ≤ 2) for first 14 days per athlete | Z-score cold-start | Low | Yes |
| Arrow entries: last write wins, source stored and shown; coach badge shown as authoritative | Approved rule | Low | Yes |
| Coach privacy enforced in app code (role gate), not DB RLS, for pilot | Streamlit uses one service connection; RLS deferred to v2 | Accepted for pilot | Yes |
| IST (Asia/Kolkata) for "today" everywhere | Camp is in Sonipat | Low | Yes |

## Deviations
| Original plan | Deviation | Reason | Impact |
|---|---|---|---|
| Run/verify full app locally | Environment has no network: streamlit/psycopg2 not installable here | Sandbox restriction | Metrics engine verified with unit tests; UI verified by user via checklist after deploy |
| pytest for tests | stdlib unittest | pytest not installable offline | None |
| Seed data written directly to DB | seed_data.py also supports CSV dry-run output | Lets user inspect fake data without DB | Positive |

## Files Changed
- schema.sql — full Supabase schema + default staff users
- app.py — router (token → athlete form; login → role views)
- lib/db.py, lib/auth.py, lib/metrics.py
- views/athlete_form.py, views/coach.py, views/physio.py, views/dashboard.py
- seed_data.py, tests/test_metrics.py, requirements.txt, README.md

## Verification
| Check | Result | Notes |
|---|---|---|
| Metrics unit tests (17: ACWR, monotony, strain, z, flags, cold starts, wt-drop, arrows) | PASS | stdlib unittest |
| E2E: seed scenarios through flag engine | PASS | steady=green, spike+cut=red, dip=red, injured=amber(low ACWR) |
| Seed dry-run CSV generation | PASS | seed_preview/*.csv |
| Python syntax compile of every file | PASS | py_compile |
| Full UI run | NOT RUN HERE | requires deploy; user checklist in README |

## Open Questions
- Should archers also record draw-weight for load context? (Deferred, easy column add.)
- Hindi labels for the athlete form? (Deferred to feedback.)

## Follow-ups
- v2: Supabase RLS + React frontend, WhatsApp nudges, PWA offline form.
