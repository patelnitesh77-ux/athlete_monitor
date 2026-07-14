"""Seed the pilot with 4 fake athletes x 5 weeks of realistic data so every
chart, flag, and cold-start behavior is visible before real data arrives.

Usage:
  DATABASE_URL=postgres://...  python seed_data.py          # writes to Supabase
  python seed_data.py --dry-run                             # writes CSVs to ./seed_preview/

Scenarios baked in:
  1. Anil  (wrestling, 65kg)  — healthy, steady load, green
  2. Bala  (wrestling, 74kg)  — acute load spike + weight cut -> red flags
  3. Chitra (archery)         — high arrow volumes, wellness dip this week
  4. Deepa  (archery)         — open shoulder injury, in Reconditioning, rehab loads
"""
from __future__ import annotations

import os
import random
import sys
from datetime import date, timedelta

random.seed(42)
TODAY = date.today()
START = TODAY - timedelta(days=34)
DRY = "--dry-run" in sys.argv

ATHLETES = [
    dict(name="Anil Kumar (demo)", sport="wrestling", weight_category="65kg", scenario="steady"),
    dict(name="Bala Singh (demo)", sport="wrestling", weight_category="74kg", scenario="spike_cut"),
    dict(name="Chitra Rao (demo)", sport="archery", weight_category=None, scenario="dip"),
    dict(name="Deepa Nair (demo)", sport="archery", weight_category=None, scenario="injured"),
]

GYM_TEMPLATES = {
    "wrestling": [("Back squat", 4, 5, 90), ("Bench press", 4, 5, 70),
                  ("Pull-ups", 4, 8, 0), ("RDL", 3, 8, 80), ("Neck harness", 3, 12, 15)],
    "archery": [("Row (cable)", 4, 10, 35), ("Face pulls", 3, 15, 20),
                ("DB shoulder press", 3, 10, 12), ("Plank", 3, 60, 0), ("Scap pull-ups", 3, 8, 0)],
}


def gen_days(a):
    """Yield per-day dicts: wellness, sessions."""
    base_wt = 66.5 if a["weight_category"] == "65kg" else 75.5
    for i in range(35):
        d = START + timedelta(days=i)
        rest = d.weekday() == 6                       # Sundays off
        out = dict(date=d, wellness=None, sessions=[])

        # ---- wellness (athletes miss ~10% of days; today handled per scenario) ----
        submit = random.random() > 0.10
        wl = dict(sleep_quality=random.choice([3, 4, 4, 5]), sleep_hours=round(random.uniform(6.5, 8.5), 1),
                  fatigue=random.choice([3, 4, 4, 5]), soreness=random.choice([3, 4, 4]),
                  stress=random.choice([3, 4, 5]), mood=random.choice([3, 4, 5]),
                  hydration=random.choice([3, 4, 5]), body_weight_kg=None,
                  pain_flag=False, pain_location=None, pain_type=None, pain_days=None)

        if a["sport"] == "wrestling":
            wl["body_weight_kg"] = round(base_wt + random.uniform(-0.4, 0.4), 1)

        if a["scenario"] == "spike_cut":
            # last 3 days: aggressive weight cut + fatigue
            if i >= 32:
                wl["body_weight_kg"] = round(base_wt - 0.9 * (i - 31), 1)   # ~ -2.4% by today
                wl["fatigue"] = 2; wl["hydration"] = 1; wl["mood"] = 2
            submit = True
        if a["scenario"] == "dip" and i >= 31:
            wl.update(sleep_quality=2, fatigue=2, soreness=2, stress=2, mood=2)
        if a["scenario"] == "injured" and i == 20:
            wl.update(pain_flag=True, pain_location="right shoulder",
                      pain_type="Sharp", pain_days=1)
        if a["scenario"] == "steady" and d == TODAY:
            submit = True

        if submit:
            out["wellness"] = wl

        # ---- load ----
        if not rest:
            if a["scenario"] == "injured" and i > 20:
                if i > 24:                            # rehab from day 25
                    out["sessions"].append(dict(type="rehab", dur=40, rpe=3, arrows=None,
                                                source="physio"))
            else:
                dur = random.choice([75, 90, 105])
                rpe = random.choice([5, 6, 6, 7])
                if a["scenario"] == "spike_cut" and i >= 28:
                    dur, rpe = 120, 9                 # acute spike week
                arrows = random.choice([120, 150, 180]) if a["sport"] == "archery" else None
                out["sessions"].append(dict(type="field", dur=dur, rpe=rpe, arrows=arrows,
                                            source="coach"))
                if d.weekday() in (1, 4):             # Tue/Fri gym
                    out["sessions"].append(dict(type="gym", dur=60,
                                                rpe=random.choice([5, 6, 7]),
                                                arrows=None, source="coach"))
        yield out


def main():
    if DRY:
        import csv
        os.makedirs("seed_preview", exist_ok=True)
        wf = csv.writer(open("seed_preview/wellness.csv", "w", newline=""))
        sf = csv.writer(open("seed_preview/sessions.csv", "w", newline=""))
        wf.writerow(["athlete", "date", "sleep_q", "fatigue", "soreness", "stress", "mood",
                     "hydration", "weight", "pain", "pain_loc"])
        sf.writerow(["athlete", "date", "type", "dur", "rpe", "load", "arrows", "source"])
        for a in ATHLETES:
            for day in gen_days(a):
                if day["wellness"]:
                    w = day["wellness"]
                    wf.writerow([a["name"], day["date"], w["sleep_quality"], w["fatigue"],
                                 w["soreness"], w["stress"], w["mood"], w["hydration"],
                                 w["body_weight_kg"], w["pain_flag"], w["pain_location"]])
                for s in day["sessions"]:
                    sf.writerow([a["name"], day["date"], s["type"], s["dur"], s["rpe"],
                                 s["dur"] * s["rpe"], s["arrows"], s["source"]])
        print("Dry run complete -> seed_preview/*.csv")
        return

    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    cur = conn.cursor()
    for a in ATHLETES:
        cur.execute("insert into athletes (name, sport, weight_category) values (%s,%s,%s) returning id",
                    (a["name"], a["sport"], a["weight_category"]))
        aid = cur.fetchone()[0]
        injury_id = None
        for day in gen_days(a):
            if day["wellness"]:
                w = day["wellness"]
                cur.execute("""insert into wellness_entries
                    (athlete_id, entry_date, sleep_quality, sleep_hours, fatigue, soreness,
                     stress, mood, hydration, body_weight_kg, pain_flag, pain_location,
                     pain_type, pain_days)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    on conflict (athlete_id, entry_date) do nothing""",
                    (aid, day["date"], w["sleep_quality"], w["sleep_hours"], w["fatigue"],
                     w["soreness"], w["stress"], w["mood"], w["hydration"],
                     w["body_weight_kg"], w["pain_flag"], w["pain_location"],
                     w["pain_type"], w["pain_days"]))
            for s in day["sessions"]:
                cur.execute("""insert into training_sessions
                    (athlete_id, session_date, session_type, duration_min, rpe, arrows, source, created_by)
                    values (%s,%s,%s,%s,%s,%s,%s,'seed') returning id""",
                    (aid, day["date"], s["type"], s["dur"], s["rpe"], s["arrows"], s["source"]))
                sid = cur.fetchone()[0]
                if s["type"] == "gym":
                    for pos, (ex, sets, reps, wt) in enumerate(GYM_TEMPLATES[a["sport"]], 1):
                        cur.execute("""insert into gym_exercises
                            (session_id, exercise, sets, reps, weight_kg, position)
                            values (%s,%s,%s,%s,%s,%s)""", (sid, ex, sets, reps, wt, pos))
        if a["scenario"] == "injured":
            onset = START + timedelta(days=20)
            cur.execute("""insert into injuries (athlete_id, onset_date, body_region, side,
                            injury_type, mechanism, severity, diagnosis_notes)
                           values (%s,%s,'right shoulder','right','tendon','training',
                                   '3-4 weeks','Supraspinatus tendinopathy (demo note)') returning id""",
                        (aid, onset))
            injury_id = cur.fetchone()[0]
            for ph, offset in [("Acute", 0), ("Rehab", 4), ("Reconditioning", 10)]:
                cur.execute("insert into rehab_phases (injury_id, phase, start_date) values (%s,%s,%s)",
                            (injury_id, ph, onset + timedelta(days=offset)))
            cur.execute("""insert into availability (athlete_id, status, restrictions, updated_by)
                           values (%s,'Modified','No overhead work; band + isometrics OK; max 60 min','seed')
                           on conflict (athlete_id) do update set status=excluded.status,
                           restrictions=excluded.restrictions""", (aid,))
    print("Seed complete: 4 demo athletes, 5 weeks of data.")


if __name__ == "__main__":
    main()
