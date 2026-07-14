"""Physio view — full medical module: pain-flag queue, injuries, rehab phases,
rehab sessions (optionally counted into load), availability + coach-facing restrictions."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from lib import db

IST = ZoneInfo("Asia/Kolkata")
PHASES = ["Acute", "Rehab", "Reconditioning", "Modified Training", "Full RTP"]
STATUSES = ["Full", "Modified", "Rehab only", "Out"]


def render(user):
    st.title("🩺 Physio Console")
    today = datetime.now(IST).date()
    aths = db.athletes()
    if aths.empty:
        st.warning("No athletes yet — ask admin to add them.")
        return
    name_of = dict(zip(aths["id"], aths["name"]))

    tab_queue, tab_inj, tab_avail = st.tabs(
        ["🚨 Today's pain reports", "Injuries & rehab", "Availability & restrictions"])

    # ---------- pain queue ----------
    with tab_queue:
        flagged = []
        for _, a in aths.iterrows():
            w = db.wellness_for(a["id"], since=today)
            if not w.empty and bool(w.iloc[0]["pain_flag"]):
                r = w.iloc[0]
                flagged.append((a["name"], r["pain_location"], r["pain_type"], r["pain_days"]))
        if not flagged:
            st.success("No new pain reports today. ✅")
        else:
            st.error(f"{len(flagged)} athlete(s) reported pain today:")
            st.dataframe(pd.DataFrame(flagged, columns=["Athlete", "Location", "Type", "Days"]),
                         hide_index=True, use_container_width=True)
            st.caption("Open 'Injuries & rehab' to create an injury record if needed.")

    # ---------- injuries & rehab ----------
    with tab_inj:
        aid = st.selectbox("Athlete", list(name_of), format_func=name_of.get)

        with st.expander("➕ New injury record"):
            with st.form("new_injury"):
                c1, c2, c3 = st.columns(3)
                onset = c1.date_input("Onset date", today)
                region = c2.text_input("Body region (e.g., right shoulder)")
                side = c3.selectbox("Side", ["left", "right", "bilateral", "n/a"])
                c4, c5, c6 = st.columns(3)
                itype = c4.selectbox("Type", ["muscle", "tendon", "ligament", "joint", "bone", "other"])
                mech = c5.selectbox("Mechanism", ["training", "competition", "gym", "non-sport", "unknown"])
                sev = c6.text_input("Severity / expected timeloss")
                dx = st.text_area("Diagnosis notes (physio-only, never shown to coaches)")
                if st.form_submit_button("Create injury", type="primary"):
                    if not region.strip():
                        st.error("Body region is required.")
                    else:
                        iid = db.add_injury(dict(athlete_id=aid, onset_date=onset,
                                                 body_region=region.strip(), side=side,
                                                 injury_type=itype, mechanism=mech,
                                                 severity=sev or None, diagnosis_notes=dx or None))
                        db.add_phase(iid, "Acute", onset, "Auto-created at injury entry")
                        st.success("Injury created (phase: Acute). Remember to update availability.")

        injs = db.injuries_for(aid)
        if injs.empty:
            st.caption("No injury records for this athlete.")
        for _, inj in injs.iterrows():
            phase_now = db.current_phase(inj["id"]) or "—"
            badge = "🟢 closed" if inj["status"] == "closed" else f"🔶 open · {phase_now}"
            with st.expander(f"{inj['onset_date']} · {inj['body_region']} ({inj['injury_type']}) · {badge}"):
                st.write(f"**Side:** {inj['side']} · **Mechanism:** {inj['mechanism']} · "
                         f"**Severity:** {inj['severity'] or '—'}")
                if inj["diagnosis_notes"]:
                    st.write(f"**Diagnosis notes:** {inj['diagnosis_notes']}")

                st.markdown("**Phase timeline**")
                ph = db.phases_for(inj["id"])
                if not ph.empty:
                    st.dataframe(ph[["start_date", "phase", "notes"]].rename(columns=str.title),
                                 hide_index=True, use_container_width=True)
                if inj["status"] == "open":
                    c1, c2, c3 = st.columns([2, 2, 1])
                    new_phase = c1.selectbox("Move to phase", PHASES, key=f"ph{inj['id']}")
                    ph_date = c2.date_input("From date", today, key=f"phd{inj['id']}")
                    if c3.button("Update", key=f"phb{inj['id']}"):
                        db.add_phase(inj["id"], new_phase, ph_date, None)
                        st.rerun()

                st.markdown("**Rehab sessions**")
                with st.form(f"rehab{inj['id']}"):
                    rc1, rc2, rc3 = st.columns(3)
                    rdate = rc1.date_input("Date", today, key=f"rd{inj['id']}")
                    rdur = rc2.number_input("Duration (min)", 0.0, 240.0, 45.0, 5.0, key=f"rdu{inj['id']}")
                    rrpe = rc3.slider("RPE", 0.0, 10.0, 3.0, 0.5, key=f"rr{inj['id']}")
                    rnotes = st.text_area("Session notes", key=f"rn{inj['id']}")
                    count_load = st.checkbox("Count this session in athlete's daily load", True,
                                             key=f"rl{inj['id']}")
                    if st.form_submit_button("Log rehab session"):
                        tsid = None
                        if count_load and rdur > 0:
                            tsid = db.add_session(aid, rdate, "rehab", rdur, rrpe, None,
                                                  "Rehab session", "physio", user["username"])
                        db.add_rehab_session(inj["id"], rdate, rnotes or None, tsid)
                        st.success("Rehab session logged.")
                rs = db.rehab_sessions_for(inj["id"])
                if not rs.empty:
                    st.dataframe(rs[["session_date", "notes"]].rename(columns=str.title),
                                 hide_index=True, use_container_width=True)

                if inj["status"] == "open" and st.button("✅ Close injury (Full RTP achieved)",
                                                         key=f"close{inj['id']}"):
                    db.add_phase(inj["id"], "Full RTP", today, "Closed")
                    db.close_injury(inj["id"])
                    st.rerun()

    # ---------- availability ----------
    with tab_avail:
        st.caption("This is exactly what coaches see — status + your do's & don'ts. Nothing else.")
        avail = db.availability_all().set_index("athlete_id")
        aid2 = st.selectbox("Athlete", list(name_of), format_func=name_of.get, key="avail_ath")
        cur_status = avail.loc[aid2, "status"] if aid2 in avail.index else "Full"
        cur_restr = (avail.loc[aid2, "restrictions"] if aid2 in avail.index else "") or ""
        with st.form("avail_form"):
            status = st.selectbox("Status", STATUSES, index=STATUSES.index(cur_status))
            restrictions = st.text_area("Restrictions / do's & don'ts for coaches", cur_restr,
                                        placeholder="e.g., No overhead pressing; mat drills OK; max 60 min sessions")
            if st.form_submit_button("Update availability", type="primary"):
                db.set_availability(aid2, status, restrictions or None, user["username"])
                st.success("Updated — visible to coaches immediately.")
