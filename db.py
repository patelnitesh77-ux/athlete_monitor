"""Postgres (Supabase) data access layer.

All reads return pandas DataFrames with numeric columns cast to float
(psycopg2 returns Decimal for numeric, which breaks numpy math).
Connection string comes from Streamlit secrets: DATABASE_URL.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import psycopg2
import psycopg2.extras
import streamlit as st

FLOAT_COLS = {"load_au", "duration_min", "rpe", "sleep_hours", "body_weight_kg", "weight_kg"}


@st.cache_resource
def _conn():
    c = psycopg2.connect(st.secrets["DATABASE_URL"])
    c.autocommit = True
    return c


def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    """SELECT -> DataFrame (floats cast)."""
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    except psycopg2.OperationalError:
        st.cache_resource.clear()               # stale connection after idle
        conn = _conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    df = pd.DataFrame(rows)
    for col in df.columns.intersection(FLOAT_COLS):
        df[col] = df[col].astype(float)
    return df


def x(sql: str, params: tuple = ()):
    """INSERT/UPDATE/DELETE. Returns first row if RETURNING used."""
    conn = _conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchone()
        except psycopg2.ProgrammingError:
            return None


# ------------------------- athletes / staff -------------------------
def athletes(active_only: bool = True) -> pd.DataFrame:
    where = "where active" if active_only else ""
    return q(f"select * from athletes {where} order by sport, name")


def athlete_by_token(token: str):
    df = q("select * from athletes where access_token=%s and active", (token,))
    return None if df.empty else df.iloc[0]


def staff_by_username(username: str):
    df = q("select * from staff_users where username=%s and active", (username,))
    return None if df.empty else df.iloc[0]


# ------------------------- wellness -------------------------
def wellness_for(athlete_id: str, since: date | None = None) -> pd.DataFrame:
    if since:
        return q("select * from wellness_entries where athlete_id=%s and entry_date>=%s order by entry_date",
                 (athlete_id, since))
    return q("select * from wellness_entries where athlete_id=%s order by entry_date", (athlete_id,))


def upsert_wellness(athlete_id: str, entry_date: date, vals: dict):
    x("""insert into wellness_entries
           (athlete_id, entry_date, sleep_quality, sleep_hours, fatigue, soreness,
            stress, mood, hydration, body_weight_kg, pain_flag, pain_location, pain_type, pain_days)
         values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
         on conflict (athlete_id, entry_date) do update set
            sleep_quality=excluded.sleep_quality, sleep_hours=excluded.sleep_hours,
            fatigue=excluded.fatigue, soreness=excluded.soreness, stress=excluded.stress,
            mood=excluded.mood, hydration=excluded.hydration,
            body_weight_kg=excluded.body_weight_kg, pain_flag=excluded.pain_flag,
            pain_location=excluded.pain_location, pain_type=excluded.pain_type,
            pain_days=excluded.pain_days""",
      (athlete_id, entry_date, vals["sleep_quality"], vals["sleep_hours"], vals["fatigue"],
       vals["soreness"], vals["stress"], vals["mood"], vals["hydration"],
       vals.get("body_weight_kg"), vals["pain_flag"], vals.get("pain_location"),
       vals.get("pain_type"), vals.get("pain_days")))


# ------------------------- sessions / gym -------------------------
def sessions_for(athlete_id: str) -> pd.DataFrame:
    return q("select * from training_sessions where athlete_id=%s order by session_date", (athlete_id,))


def add_session(athlete_id: str, session_date: date, session_type: str, duration_min: float,
                rpe: float, arrows, notes, source: str, created_by: str):
    row = x("""insert into training_sessions
                 (athlete_id, session_date, session_type, duration_min, rpe, arrows, notes, source, created_by)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
            (athlete_id, session_date, session_type, duration_min, rpe, arrows, notes, source, created_by))
    return row["id"]


def add_gym_exercise(session_id: str, exercise: str, sets: int, reps: int, weight_kg: float, position: int):
    x("insert into gym_exercises (session_id, exercise, sets, reps, weight_kg, position) values (%s,%s,%s,%s,%s,%s)",
      (session_id, exercise, sets, reps, weight_kg, position))


def gym_for_session(session_id: str) -> pd.DataFrame:
    return q("select * from gym_exercises where session_id=%s order by position", (session_id,))


def last_gym_session(athlete_id: str):
    df = q("""select id, session_date from training_sessions
              where athlete_id=%s and session_type='gym' order by session_date desc limit 1""", (athlete_id,))
    return None if df.empty else df.iloc[0]


# ------------------------- medical -------------------------
def injuries_for(athlete_id: str | None = None, open_only: bool = False) -> pd.DataFrame:
    cond, params = [], []
    if athlete_id:
        cond.append("athlete_id=%s"); params.append(athlete_id)
    if open_only:
        cond.append("status='open'")
    where = ("where " + " and ".join(cond)) if cond else ""
    return q(f"select * from injuries {where} order by onset_date desc", tuple(params))


def add_injury(vals: dict):
    row = x("""insert into injuries (athlete_id, onset_date, body_region, side, injury_type,
                                     mechanism, severity, diagnosis_notes)
               values (%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
            (vals["athlete_id"], vals["onset_date"], vals["body_region"], vals["side"],
             vals["injury_type"], vals["mechanism"], vals.get("severity"), vals.get("diagnosis_notes")))
    return row["id"]


def close_injury(injury_id: str):
    x("update injuries set status='closed' where id=%s", (injury_id,))


def phases_for(injury_id: str) -> pd.DataFrame:
    return q("select * from rehab_phases where injury_id=%s order by start_date", (injury_id,))


def add_phase(injury_id: str, phase: str, start_date: date, notes):
    x("insert into rehab_phases (injury_id, phase, start_date, notes) values (%s,%s,%s,%s)",
      (injury_id, phase, start_date, notes))


def current_phase(injury_id: str):
    df = q("select phase from rehab_phases where injury_id=%s order by start_date desc limit 1", (injury_id,))
    return None if df.empty else df.iloc[0]["phase"]


def add_rehab_session(injury_id: str, session_date: date, notes, training_session_id):
    x("insert into rehab_sessions (injury_id, session_date, notes, training_session_id) values (%s,%s,%s,%s)",
      (injury_id, session_date, notes, training_session_id))


def rehab_sessions_for(injury_id: str) -> pd.DataFrame:
    return q("select * from rehab_sessions where injury_id=%s order by session_date desc", (injury_id,))


# ------------------------- availability (coach-visible) -------------------------
def availability_all() -> pd.DataFrame:
    return q("""select a.id as athlete_id, coalesce(av.status,'Full') as status, av.restrictions
                from athletes a left join availability av on av.athlete_id=a.id where a.active""")


def set_availability(athlete_id: str, status: str, restrictions, updated_by: str):
    x("""insert into availability (athlete_id, status, restrictions, updated_by, updated_at)
         values (%s,%s,%s,%s, now())
         on conflict (athlete_id) do update set status=excluded.status,
             restrictions=excluded.restrictions, updated_by=excluded.updated_by, updated_at=now()""",
      (athlete_id, status, restrictions, updated_by))


# ------------------------- admin -------------------------
def add_athlete(name: str, sport: str, weight_category):
    row = x("insert into athletes (name, sport, weight_category) values (%s,%s,%s) returning access_token",
            (name, sport, weight_category))
    return row["access_token"]


def set_staff_password(username: str, salt: str, pw_hash: str):
    x("update staff_users set pw_salt=%s, pw_hash=%s where username=%s", (salt, pw_hash, username))
