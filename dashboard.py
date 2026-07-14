"""Monitoring dashboard — landing view is wellness compliance, then squad grid,
then per-athlete detail. Role-aware: coaches never see medical detail."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from lib import db, metrics as M

IST = ZoneInfo("Asia/Kolkata")
LEVEL_ICON = {"green": "🟢", "amber": "🟡", "red": "🔴"}
STATUS_ICON = {"Full": "🟢", "Modified": "🟡", "Rehab only": "🟠", "Out": "🔴"}


def _athlete_bundle(athlete_id: str, today):
    sessions = db.sessions_for(athlete_id)
    wellness = db.wellness_for(athlete_id)
    daily = M.daily_load_series(sessions, today)
    return sessions, wellness, daily


def render(user):
    today = datetime.now(IST).date()
    st.title("📊 Squad Monitor")
    st.caption(f"{today.strftime('%A, %d %b %Y')} · role: {user['role']}")

    aths = db.athletes()
    if aths.empty:
        st.warning("No athletes yet — add them in the Admin panel.")
        return
    avail = db.availability_all().set_index("athlete_id")

    # ================= 1. COMPLIANCE PANEL (morning-first view) =================
    st.header("1 · Wellness form compliance")
    missing, done = [], []
    bundles = {}
    for _, a in aths.iterrows():
        sessions, wellness, daily = _athlete_bundle(a["id"], today)
        bundles[a["id"]] = (sessions, wellness, daily)
        submitted = (not wellness.empty) and \
            (today in set(pd.to_datetime(wellness["entry_date"]).dt.date))
        (done if submitted else missing).append(a["name"])
    c1, c2 = st.columns(2)
    c1.metric("Submitted", f"{len(done)} / {len(aths)}")
    c2.metric("Missing", len(missing))
    if missing:
        st.warning("Not yet submitted: " + ", ".join(missing))
        nudge = ("Good morning! ☀️ Gentle reminder to fill your daily wellness form "
                 "before training: " + ", ".join(missing))
        st.code(nudge, language=None)
        st.caption("Copy-paste this into the athlete WhatsApp group.")
    else:
        st.success("Everyone has submitted today. 🎉")

    st.divider()

    # ================= 2. SQUAD GRID =================
    st.header("2 · Squad grid")
    rows = []
    flag_details = {}
    for _, a in aths.iterrows():
        sessions, wellness, daily = bundles[a["id"]]
        flags = M.compute_flags(on=today, sport=a["sport"], daily=daily, wellness=wellness)
        flag_details[a["id"]] = flags
        ratio = M.acwr(daily, today)
        wk_load = M.weekly_load(daily, today)
        stat = avail.loc[a["id"], "status"] if a["id"] in avail.index else "Full"

        # wellness today (mean of 6 items)
        w_today = "—"
        if not wellness.empty:
            wl = wellness.copy()
            wl["entry_date"] = pd.to_datetime(wl["entry_date"]).dt.date
            trow = wl[wl["entry_date"] == today]
            if not trow.empty:
                w_today = f"{trow.iloc[0][M.WELLNESS_ITEMS].astype(float).mean():.1f}/5"

        # weight trend (wrestlers): last vs 7 days ago
        wt_trend = "—"
        if a["sport"] == "wrestling" and not wellness.empty:
            wl = wellness.dropna(subset=["body_weight_kg"]).copy()
            if not wl.empty:
                wl["entry_date"] = pd.to_datetime(wl["entry_date"]).dt.date
                wl = wl.sort_values("entry_date")
                last_w = float(wl.iloc[-1]["body_weight_kg"])
                week_ago = wl[wl["entry_date"] <= today - timedelta(days=7)]
                if not week_ago.empty:
                    delta = last_w - float(week_ago.iloc[-1]["body_weight_kg"])
                    wt_trend = f"{last_w:.1f} kg ({delta:+.1f})"
                else:
                    wt_trend = f"{last_w:.1f} kg"

        arrows_wk = M.weekly_arrows(sessions, today) if a["sport"] == "archery" else None
        rows.append({
            "id": a["id"], "Athlete": a["name"], "Sport": a["sport"].title(),
            "Availability": f"{STATUS_ICON.get(stat,'')} {stat}",
            "Wellness today": w_today,
            "Flag": LEVEL_ICON[flags.level],
            "Why": "; ".join(flags.reasons[:3]) or "—",
            "ACWR": f"{ratio:.2f}" if ratio is not None else "building…",
            "Weekly load": f"{wk_load:,.0f}",
            "Body wt": wt_trend if a["sport"] == "wrestling" else "—",
            "Arrows (7d)": arrows_wk if arrows_wk is not None else "—",
        })

    grid = pd.DataFrame(rows)
    order = {"🔴": 0, "🟡": 1, "🟢": 2}
    grid = grid.sort_values("Flag", key=lambda s: s.map(order))
    st.dataframe(grid.drop(columns=["id"]), hide_index=True, use_container_width=True)
    st.caption("🔴 red flag · 🟡 watch · 🟢 ok · ACWR shows 'building…' until 28 days of load history")

    st.divider()

    # ================= 3. ATHLETE DETAIL =================
    st.header("3 · Athlete detail")
    name_of = dict(zip(aths["id"], aths["name"]))
    aid = st.selectbox("Select athlete", list(name_of), format_func=name_of.get)
    a = aths[aths["id"] == aid].iloc[0]
    sessions, wellness, daily = bundles[aid]
    flags = flag_details[aid]

    if flags.reasons:
        (st.error if flags.level == "red" else st.warning if flags.level == "amber" else st.info)(
            f"{LEVEL_ICON[flags.level]} " + " · ".join(flags.reasons))

    t_load, t_well, t_gym, t_med = st.tabs(["Load & ACWR", "Wellness trends", "Gym history", "Injury / rehab"])

    with t_load:
        if daily.empty:
            st.caption("No load data yet.")
        else:
            df = pd.DataFrame({"date": list(daily.index), "daily load (AU)": daily.values}).set_index("date")
            st.bar_chart(df, height=220)
            acwr_series = {d: M.acwr(daily, d) for d in daily.index}
            acwr_df = pd.DataFrame({"date": list(acwr_series), "ACWR": list(acwr_series.values())}
                                   ).dropna().set_index("date")
            if not acwr_df.empty:
                st.line_chart(acwr_df, height=220)
            mono, strain = M.monotony_strain(daily, today)
            c1, c2, c3 = st.columns(3)
            c1.metric("Weekly load", f"{M.weekly_load(daily, today):,.0f} AU")
            c2.metric("Monotony", f"{mono:.2f}" if mono else "—")
            c3.metric("Strain", f"{strain:,.0f}" if strain else "—")

    with t_well:
        if wellness.empty:
            st.caption("No wellness entries yet.")
        else:
            wdf = wellness.copy()
            wdf["entry_date"] = pd.to_datetime(wdf["entry_date"])
            plot = wdf.set_index("entry_date")[M.WELLNESS_ITEMS].astype(float)
            st.line_chart(plot, height=260)
            if a["sport"] == "wrestling":
                bw = wdf.dropna(subset=["body_weight_kg"]).set_index("entry_date")[["body_weight_kg"]]
                if not bw.empty:
                    st.line_chart(bw.astype(float), height=180)
            pains = wdf[wdf["pain_flag"] == True]  # noqa: E712
            if not pains.empty:
                st.markdown("**Pain reports**")
                st.dataframe(pains[["entry_date", "pain_location", "pain_type", "pain_days"]]
                             .rename(columns=str.title), hide_index=True, use_container_width=True)

    with t_gym:
        gym = sessions[sessions["session_type"] == "gym"].sort_values("session_date", ascending=False) \
            if not sessions.empty else pd.DataFrame()
        if gym.empty:
            st.caption("No gym sessions yet.")
        else:
            for _, g in gym.head(8).iterrows():
                with st.expander(f"{g['session_date']} · {g['duration_min']:.0f} min · load {g['load_au']:.0f} AU"):
                    ex = db.gym_for_session(g["id"])
                    if ex.empty:
                        st.caption("No exercises recorded.")
                    else:
                        ex["tonnage"] = ex["sets"] * ex["reps"] * ex["weight_kg"]
                        st.dataframe(ex[["exercise", "sets", "reps", "weight_kg", "tonnage"]]
                                     .rename(columns=str.title), hide_index=True, use_container_width=True)

    with t_med:
        if user["role"] == "coach":
            stat = avail.loc[aid, "status"] if aid in avail.index else "Full"
            restr = (avail.loc[aid, "restrictions"] if aid in avail.index else None) or "None given"
            st.metric("Availability", stat)
            st.markdown(f"**Physio restrictions / do's & don'ts:** {restr}")
            st.caption("Full medical details are visible to physio and admin only.")
        else:
            injs = db.injuries_for(aid)
            if injs.empty:
                st.caption("No injury records.")
            for _, inj in injs.iterrows():
                phase_now = db.current_phase(inj["id"]) or "—"
                st.markdown(f"**{inj['onset_date']} · {inj['body_region']} ({inj['injury_type']})** — "
                            f"{'closed' if inj['status']=='closed' else 'open · ' + phase_now}")
                ph = db.phases_for(inj["id"])
                if not ph.empty:
                    st.dataframe(ph[["start_date", "phase", "notes"]].rename(columns=str.title),
                                 hide_index=True, use_container_width=True)
