"""Athlete view — opened via private token link. Wellness form (+ arrows for archers).
Designed for a phone: sliders/selects, one screen, <60s."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from lib import db

IST = ZoneInfo("Asia/Kolkata")
SCALE_HELP = "1 = very poor · 5 = excellent"


def render(athlete):
    today = datetime.now(IST).date()
    st.title(f"👋 {athlete['name']}")
    st.caption(f"{athlete['sport'].title()} · Daily check-in for {today.strftime('%d %b %Y')}")

    existing = db.wellness_for(athlete["id"], since=today)
    already = not existing.empty
    if already:
        st.success("You've already submitted today. You can update and resubmit below.")
    prev = existing.iloc[0] if already else None

    def dflt(key, fallback):
        return int(prev[key]) if already and prev[key] is not None else fallback

    with st.form("wellness"):
        st.subheader("How are you today?")
        c1, c2 = st.columns(2)
        with c1:
            sleep_quality = st.slider("😴 Sleep quality", 1, 5, dflt("sleep_quality", 3), help=SCALE_HELP)
            fatigue = st.slider("🔋 Energy (1 = exhausted)", 1, 5, dflt("fatigue", 3))
            soreness = st.slider("💪 Muscles (1 = very sore)", 1, 5, dflt("soreness", 3))
            hydration = st.slider("💧 Hydration", 1, 5, dflt("hydration", 3))
        with c2:
            sleep_hours = st.number_input("🕐 Hours slept", 0.0, 14.0,
                                          float(prev["sleep_hours"]) if already else 8.0, 0.5)
            stress = st.slider("🧠 Stress (1 = very stressed)", 1, 5, dflt("stress", 3))
            mood = st.slider("🙂 Mood", 1, 5, dflt("mood", 3))

        body_weight = None
        if athlete["sport"] == "wrestling":
            st.subheader("⚖️ Body weight")
            bw_default = float(prev["body_weight_kg"]) if already and prev["body_weight_kg"] else 0.0
            body_weight = st.number_input("Today's weight (kg) — morning, before breakfast",
                                          0.0, 200.0, bw_default, 0.1)

        arrows = None
        if athlete["sport"] == "archery":
            st.subheader("🏹 Arrows shot today")
            arrows = st.number_input("Total arrows so far today (leave 0 if coach logs it)", 0, 1000, 0, 10)

        st.subheader("🩹 Any pain or discomfort?")
        pain_flag = st.toggle("Yes, I have pain today")
        pain_location = pain_type = None
        pain_days = None
        if pain_flag:
            pain_location = st.text_input("Where is it? (e.g., right shoulder, lower back)")
            pain_type = st.selectbox("What kind of pain?",
                                     ["Dull ache", "Sharp", "Throbbing", "Stiffness",
                                      "Burning", "Pins & needles", "Other"])
            pain_days = st.number_input("Since how many days?", 1, 365, 1)

        submitted = st.form_submit_button("Submit ✅", use_container_width=True, type="primary")

    if submitted:
        if pain_flag and not (pain_location or "").strip():
            st.error("Please tell us where the pain is so the physio can follow up.")
            return
        db.upsert_wellness(athlete["id"], today, dict(
            sleep_quality=sleep_quality, sleep_hours=sleep_hours, fatigue=fatigue,
            soreness=soreness, stress=stress, mood=mood, hydration=hydration,
            body_weight_kg=body_weight if (body_weight or 0) > 0 else None,
            pain_flag=pain_flag, pain_location=pain_location,
            pain_type=pain_type, pain_days=pain_days))
        if athlete["sport"] == "archery" and arrows and arrows > 0:
            entry_day = today  # coach entry overrides in UI
            db.add_session(athlete["id"], entry_day, "field", duration_min=1, rpe=0,
                           arrows=int(arrows), notes="Athlete-reported arrow count",
                           source="athlete", created_by="athlete-link")
        st.success("Saved — thank you! 🎉 See you tomorrow.")
        st.balloons()
