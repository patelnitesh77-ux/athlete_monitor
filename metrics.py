"""Metrics engine for the athlete monitoring pilot.

Pure pandas/numpy — no streamlit, no DB. Every function takes plain
DataFrames so it can be unit-tested offline and reused in the v2 backend.

Conventions
-----------
- "daily load" = sum of load_au (duration_min * RPE) across ALL session
  types (field + gym + rehab) for one athlete on one calendar date.
  Days with no sessions count as 0 within the athlete's active window.
- ACWR = mean daily load over last 7 days / mean daily load over last 28
  days (rolling-average method). Returned as None ("insufficient data")
  until the athlete has >= MIN_CHRONIC_DAYS days of history since their
  first recorded session, or when chronic mean is 0.
- Wellness z-score = (today - trailing BASELINE_DAYS mean) / trailing SD,
  computed per item, excluding today from the baseline. Until an athlete
  has >= MIN_BASELINE_ENTRIES wellness entries, z-flags fall back to
  absolute thresholds (any item <= ABS_LOW).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

# ---- tunables (approved thresholds) ----
MIN_CHRONIC_DAYS = 28
BASELINE_DAYS = 21
MIN_BASELINE_ENTRIES = 14
ABS_LOW = 2                    # cold-start: any wellness item <= 2 -> red
Z_RED = -1.5
Z_AMBER = -1.0
ACWR_RED_HIGH = 1.5
ACWR_AMBER_HIGH = 1.3
ACWR_AMBER_LOW = 0.8
WT_DROP_RED_PCT = 2.0          # wrestler body-weight drop over 48 h
WELLNESS_ITEMS = ["sleep_quality", "fatigue", "soreness", "stress", "mood", "hydration"]


# --------------------------------------------------------------------------
# Load series
# --------------------------------------------------------------------------
def daily_load_series(sessions: pd.DataFrame, upto: date) -> pd.Series:
    """Sessions df needs columns: session_date (date), load_au (float).
    Returns a continuous daily series (0-filled) from first session to `upto`.
    Empty input -> empty series."""
    if sessions is None or sessions.empty:
        return pd.Series(dtype=float)
    s = sessions.copy()
    s["session_date"] = pd.to_datetime(s["session_date"]).dt.date
    daily = s.groupby("session_date")["load_au"].sum()
    start = min(daily.index)
    idx = pd.date_range(start, upto, freq="D").date
    return daily.reindex(idx, fill_value=0.0).astype(float)


def acwr(daily: pd.Series, on: date) -> Optional[float]:
    """Rolling-average ACWR on a given date. None if insufficient history."""
    if daily.empty or on not in daily.index:
        return None
    pos = list(daily.index).index(on)
    history_days = pos + 1
    if history_days < MIN_CHRONIC_DAYS:
        return None
    acute = daily.iloc[pos - 6 : pos + 1].mean()
    chronic = daily.iloc[pos - 27 : pos + 1].mean()
    if chronic <= 0:
        return None
    return float(acute / chronic)


def weekly_load(daily: pd.Series, on: date) -> float:
    """Sum of daily load over the 7 days ending on `on`."""
    if daily.empty:
        return 0.0
    sub = daily[[d for d in daily.index if on - timedelta(days=6) <= d <= on]]
    return float(sub.sum())


def monotony_strain(daily: pd.Series, on: date) -> tuple[Optional[float], Optional[float]]:
    """Foster monotony (mean/SD of daily load, 7 days incl. rest days) and
    strain (weekly load * monotony). None when SD == 0 or < 7 days data."""
    if daily.empty:
        return None, None
    window = [on - timedelta(days=i) for i in range(6, -1, -1)]
    vals = [float(daily.get(d, 0.0)) for d in window]
    first = min(daily.index)
    if first > window[0]:                      # fewer than 7 days of history
        return None, None
    sd = float(np.std(vals, ddof=1))
    if sd == 0:
        return None, None
    mono = float(np.mean(vals)) / sd
    return mono, mono * float(np.sum(vals))


# --------------------------------------------------------------------------
# Wellness z-scores
# --------------------------------------------------------------------------
def wellness_z(entries: pd.DataFrame, on: date) -> dict[str, Optional[float]]:
    """entries: one row per day, columns include entry_date + WELLNESS_ITEMS.
    Returns {item: z or None}. Baseline = trailing BASELINE_DAYS excluding
    today; needs >= MIN_BASELINE_ENTRIES prior entries and SD > 0."""
    out: dict[str, Optional[float]] = {i: None for i in WELLNESS_ITEMS}
    if entries is None or entries.empty:
        return out
    e = entries.copy()
    e["entry_date"] = pd.to_datetime(e["entry_date"]).dt.date
    today_rows = e[e["entry_date"] == on]
    if today_rows.empty:
        return out
    today = today_rows.iloc[0]
    base = e[(e["entry_date"] < on) & (e["entry_date"] >= on - timedelta(days=BASELINE_DAYS))]
    if len(base) < MIN_BASELINE_ENTRIES:
        return out
    for item in WELLNESS_ITEMS:
        mu = float(base[item].mean())
        sd = float(base[item].std(ddof=1))
        if sd == 0:
            out[item] = None
        else:
            out[item] = (float(today[item]) - mu) / sd
    return out


# --------------------------------------------------------------------------
# Flags
# --------------------------------------------------------------------------
@dataclass
class FlagResult:
    level: str = "green"                # green | amber | red
    reasons: list[str] = field(default_factory=list)

    def raise_to(self, level: str, reason: str) -> None:
        order = {"green": 0, "amber": 1, "red": 2}
        if order[level] > order[self.level]:
            self.level = level
        self.reasons.append(reason)


def compute_flags(
    *,
    on: date,
    sport: str,
    daily: pd.Series,
    wellness: pd.DataFrame,
) -> FlagResult:
    """Combine all approved flag rules for one athlete on one date."""
    f = FlagResult()

    # --- missed wellness form (amber) ---
    w = wellness.copy() if wellness is not None else pd.DataFrame()
    if not w.empty:
        w["entry_date"] = pd.to_datetime(w["entry_date"]).dt.date
    submitted_today = (not w.empty) and (on in set(w["entry_date"]))
    if not submitted_today:
        f.raise_to("amber", "No wellness form today")

    # --- pain (red) ---
    if submitted_today:
        row = w[w["entry_date"] == on].iloc[0]
        if bool(row.get("pain_flag", False)):
            loc = row.get("pain_location") or "unspecified"
            f.raise_to("red", f"Pain reported ({loc})")

    # --- wellness z / absolute (red / amber) ---
    if submitted_today:
        zs = wellness_z(w, on)
        have_z = any(v is not None for v in zs.values())
        if have_z:
            for item, z in zs.items():
                if z is None:
                    continue
                if z <= Z_RED:
                    f.raise_to("red", f"{item} z={z:.1f}")
                elif z <= Z_AMBER:
                    f.raise_to("amber", f"{item} z={z:.1f}")
        else:  # cold start: absolute rule
            row = w[w["entry_date"] == on].iloc[0]
            for item in WELLNESS_ITEMS:
                if float(row[item]) <= ABS_LOW:
                    f.raise_to("red", f"{item} low ({int(row[item])}/5, baseline building)")

    # --- ACWR (red / amber) ---
    ratio = acwr(daily, on)
    if ratio is not None:
        if ratio > ACWR_RED_HIGH:
            f.raise_to("red", f"ACWR {ratio:.2f} > {ACWR_RED_HIGH}")
        elif ratio >= ACWR_AMBER_HIGH:
            f.raise_to("amber", f"ACWR {ratio:.2f} elevated")
        elif ratio < ACWR_AMBER_LOW:
            f.raise_to("amber", f"ACWR {ratio:.2f} low")

    # --- wrestler weight drop >= 2% in 48 h (red) ---
    if sport == "wrestling" and not w.empty and "body_weight_kg" in w.columns:
        wt = w.dropna(subset=["body_weight_kg"]).sort_values("entry_date")
        wt = wt[wt["entry_date"] <= on]
        if len(wt) >= 2:
            latest = wt.iloc[-1]
            window = wt[wt["entry_date"] >= latest["entry_date"] - timedelta(days=2)]
            if len(window) >= 2:
                start_w = float(window.iloc[0]["body_weight_kg"])
                end_w = float(latest["body_weight_kg"])
                if start_w > 0:
                    drop_pct = (start_w - end_w) / start_w * 100.0
                    if drop_pct >= WT_DROP_RED_PCT:
                        f.raise_to("red", f"Weight -{drop_pct:.1f}% in 48h")
    return f


def weekly_arrows(sessions: pd.DataFrame, on: date) -> int:
    """Total arrows over the 7 days ending on `on` (archers)."""
    if sessions is None or sessions.empty or "arrows" not in sessions.columns:
        return 0
    s = sessions.copy()
    s["session_date"] = pd.to_datetime(s["session_date"]).dt.date
    mask = (s["session_date"] >= on - timedelta(days=6)) & (s["session_date"] <= on)
    return int(s.loc[mask, "arrows"].fillna(0).sum())
