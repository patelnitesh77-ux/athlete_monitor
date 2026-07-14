"""Coach / S&C view — log field sessions (sRPE), gym sessions (set/rep/weight),
arrow counts; see availability + physio restrictions ONLY (no medical detail)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from lib import db

IST = ZoneInfo("Asia/Kolkata")
STATUS_BADGE = {"Full": "🟢 Full", "Modified": "🟡 Modified",
                "Rehab only": "🟠 Rehab only", "Out": "🔴 Out"}


def _athlete_picker(key: str):
    aths = db.athletes()
    if aths.empty:
        st.warning("No athletes yet — ask admin to add them.")
        return None, aths
    avail = db.availability_all().set_index("athlete_id")
    labels = {}
    for _, a in aths.iterrows():
        stat = avail.loc[a["id"], "status"] if a["id"] in avail.index else "Full"
        labels[a["id"]] = f"{a['name']} · {a['sport']} · {STATUS_BADGE.get(stat, stat)}"
    aid = st.selectbox("Athlete", list(labels), format_func=labels.get, key=key)
    row = aths[aths["id"] == aid].iloc[0]
    if aid in avail.index and (avail.loc[aid, "restrictions"] or "").strip():
        st.info(f"📋 **Physio restrictions:** {avail.loc[aid, 'restrictions']}")
    return row, aths


def render(user):
    st.title("🏋️ Coach Console")
    today = datetime.now(IST).date()
    tab_field, tab_gym, tab_recent = st.tabs(["Field / Mat session", "Gym session", "Recent entries"])

    # ---------------- field session (sRPE) ----------------
    with tab_field:
        athlete, _ = _athlete_picker("field_ath")
        if athlete is not None:
            with st.form("field_form"):
                c1, c2, c3 = st.columns(3)
                sdate = c1.date_input("Date", today)
                duration = c2.number_input("Duration (min)", 5.0, 400.0, 90.0, 5.0)
                rpe = c3.slider("Session RPE (0–10)", 0.0, 10.0, 6.0, 0.5)
                arrows = None
                if athlete["sport"] == "archery":
                    arrows = st.number_input("🏹 Arrows shot", 0, 1000, 0, 10,
                                             help="Coach entry is authoritative — overrides athlete-reported counts in views.")
                notes = st.text_input("Notes (optional)")
                if st.form_submit_button("Save session", type="primary"):
                    db.add_session(athlete["id"], sdate, "field", duration, rpe,
                                   int(arrows) if arrows else None, notes or None,
                                   "coach", user["username"])
                    st.success(f"Saved · load = {duration * rpe:.0f} AU")

    # ---------------- gym session ----------------
    with tab_gym:
        athlete, _ = _athlete_picker("gym_ath")
        if athlete is not None:
            last = db.last_gym_session(athlete["id"])
            n_default = 5
            preload = []
            if last is not None:
                prev_ex = db.gym_for_session(last["id"])
                if not prev_ex.empty and st.toggle(
                        f"↩️ Start from last gym session ({last['session_date']})", value=True):
                    preload = prev_ex.to_dict("records")
                    n_default = len(preload)

            n_rows = st.number_input("Number of exercises", 1, 15, n_default)
            with st.form("gym_form"):
                c1, c2, c3 = st.columns(3)
                sdate = c1.date_input("Date", today, key="gymdate")
                duration = c2.number_input("Duration (min)", 5.0, 240.0, 60.0, 5.0)
                rpe = c3.slider("Gym session RPE", 0.0, 10.0, 6.0, 0.5, key="gymrpe")
                rows = []
                for i in range(int(n_rows)):
                    p = preload[i] if i < len(preload) else {}
                    e1, e2, e3, e4 = st.columns([3, 1, 1, 1])
                    ex = e1.text_input(f"Exercise {i+1}", p.get("exercise", ""), key=f"ex{i}")
                    sets = e2.number_input("Sets", 1, 15, int(p.get("sets", 3)), key=f"s{i}")
                    reps = e3.number_input("Reps", 1, 50, int(p.get("reps", 5)), key=f"r{i}")
                    wt = e4.number_input("Kg", 0.0, 500.0, float(p.get("weight_kg", 20.0)), 2.5, key=f"w{i}")
                    rows.append((ex, sets, reps, wt))
                if st.form_submit_button("Save gym session", type="primary"):
                    sid = db.add_session(athlete["id"], sdate, "gym", duration, rpe,
                                         None, None, "coach", user["username"])
                    pos = 1
                    for ex, sets, reps, wt in rows:
                        if ex.strip():
                            db.add_gym_exercise(sid, ex.strip(), int(sets), int(reps), float(wt), pos)
                            pos += 1
                    tonnage = sum(s * r * w for e, s, r, w in rows if e.strip())
                    st.success(f"Saved · sRPE load = {duration * rpe:.0f} AU · tonnage = {tonnage:,.0f} kg")

    # ---------------- recent ----------------
    with tab_recent:
        athlete, _ = _athlete_picker("recent_ath")
        if athlete is not None:
            sess = db.sessions_for(athlete["id"])
            if sess.empty:
                st.caption("No sessions yet.")
            else:
                sess = sess.sort_values("session_date", ascending=False).head(20)
                show = sess[["session_date", "session_type", "duration_min", "rpe",
                             "load_au", "arrows", "source", "notes"]].rename(columns={
                    "session_date": "Date", "session_type": "Type", "duration_min": "Min",
                    "rpe": "RPE", "load_au": "Load (AU)", "arrows": "Arrows",
                    "source": "Entered by", "notes": "Notes"})
                st.dataframe(show, use_container_width=True, hide_index=True)
