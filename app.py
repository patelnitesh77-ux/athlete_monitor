"""Athlete Monitoring Pilot — entry point / router.

Routing:
  ?token=<athlete token>  -> athlete wellness form only (no login)
  otherwise               -> staff login -> role views
     admin  : Dashboard + Coach + Physio + Admin panel
     coach  : Dashboard + Coach console (availability + restrictions only)
     physio : Dashboard + Physio console
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Athlete Monitor", page_icon="🏅", layout="wide",
                   initial_sidebar_state="collapsed")

from lib import auth, db  # noqa: E402
from views import athlete_form, coach, physio, dashboard  # noqa: E402


def admin_panel(user):
    st.title("⚙️ Admin")
    tab_a, tab_p = st.tabs(["Athletes & links", "Staff passwords"])

    with tab_a:
        with st.form("add_athlete"):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Name")
            sport = c2.selectbox("Sport", ["wrestling", "archery"])
            wcat = c3.text_input("Weight category (wrestlers)", "")
            if st.form_submit_button("Add athlete", type="primary"):
                if name.strip():
                    token = db.add_athlete(name.strip(), sport, wcat or None)
                    st.success(f"Added. Private link token: `{token}`")
                else:
                    st.error("Name required.")
        aths = db.athletes(active_only=False)
        if not aths.empty:
            st.markdown("**Private links** — share each athlete's link privately (WhatsApp DM):")
            base = st.text_input("Your deployed app URL", "https://YOUR-APP.streamlit.app")
            links = aths[["name", "sport", "access_token"]].copy()
            links["private link"] = base.rstrip("/") + "/?token=" + links["access_token"]
            st.dataframe(links[["name", "sport", "private link"]], hide_index=True,
                         use_container_width=True)

    with tab_p:
        st.caption("Reset any staff member's password.")
        with st.form("pwreset"):
            uname = st.text_input("Username")
            newpw = st.text_input("New password", type="password")
            if st.form_submit_button("Reset password"):
                if db.staff_by_username(uname.strip().lower()) is None:
                    st.error("No such user.")
                elif len(newpw) < 8:
                    st.error("Use at least 8 characters.")
                else:
                    salt = auth.new_salt()
                    db.set_staff_password(uname.strip().lower(), salt,
                                          auth.hash_password(newpw, salt))
                    st.success("Password updated.")


def staff_app(user):
    role = user["role"]
    pages = {"📊 Dashboard": lambda: dashboard.render(user)}
    if role in ("coach", "admin"):
        pages["🏋️ Coach console"] = lambda: coach.render(user)
    if role in ("physio", "admin"):
        pages["🩺 Physio console"] = lambda: physio.render(user)
    if role == "admin":
        pages["⚙️ Admin"] = lambda: admin_panel(user)

    with st.sidebar:
        st.markdown(f"**{user['display_name']}** · {role}")
        choice = st.radio("Go to", list(pages), label_visibility="collapsed")
        if st.button("Log out"):
            st.session_state.clear()
            st.rerun()
    pages[choice]()


def main():
    token = st.query_params.get("token")
    if token:
        athlete = db.athlete_by_token(token)
        if athlete is None:
            st.error("This link is not valid. Please ask your coach for a new link.")
            return
        athlete_form.render(athlete)
        return

    if "staff_user" in st.session_state:
        staff_app(st.session_state["staff_user"])
        return

    st.title("🏅 Athlete Monitor — Staff Login")
    st.caption("Athletes: use your private link instead of logging in.")
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Log in", type="primary"):
            user = auth.login_staff(u, p)
            if user is None:
                st.error("Wrong username or password.")
            else:
                st.session_state["staff_user"] = {
                    "username": user["username"],
                    "display_name": user["display_name"],
                    "role": user["role"],
                }
                st.rerun()


main()
