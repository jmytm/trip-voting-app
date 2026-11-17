"""Trip voting: run with `python -m streamlit run app.py`."""
import hashlib
import hmac
import os
import secrets
import sqlite3
import streamlit as st
import pandas as pd
import altair as alt
from db import initialize, connect, rows, setting, set_setting, shared_rules, save_shared_rules

st.set_page_config(page_title="Group Trip Voting", page_icon="🌏", layout="wide")
initialize()

def admin_secret():
    try:
        return st.secrets.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", ""))
    except (FileNotFoundError, KeyError):
        return os.environ.get("ADMIN_PASSWORD", "")

def hash_pin(pin):
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000)
    return salt + ":" + derived.hex()

def verify_pin(pin, stored):
    try:
        salt, expected = stored.split(":", 1)
        actual = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False

def get_people():
    return rows("SELECT id, name, budget FROM participants ORDER BY name")

def get_destinations():
    return rows("SELECT id, name, min_tokens, max_tokens FROM destinations ORDER BY name")

def validate(allocation, budget, destinations):
    if sum(allocation.values()) != budget:
        return f"Allocate exactly {budget} tokens (currently {sum(allocation.values())})."
    for d in destinations:
        amount = allocation.get(d["id"], 0)
        if amount < 0 or (amount != 0 and not d["min_tokens"] <= amount <= d["max_tokens"]):
            return f"{d['name']}: choose 0 or {d['min_tokens']}–{d['max_tokens']} tokens."
    return None

def save_votes(participant_id, allocation):
    # Recheck inside one write transaction so admin changes and voting cannot race.
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT value FROM settings WHERE key='voting_open'").fetchone()[0] != "true":
            raise ValueError("Voting is closed.")
        person = db.execute("SELECT budget FROM participants WHERE id=?", (participant_id,)).fetchone()
        if person is None:
            raise ValueError("Participant no longer exists.")
        destinations = [dict(r) for r in db.execute("SELECT * FROM destinations")]
        if set(allocation) != {d["id"] for d in destinations}:
            raise ValueError("Destination list changed. Reload the page.")
        problem = validate(allocation, person["budget"], destinations)
        if problem:
            raise ValueError(problem)
        db.execute("DELETE FROM votes WHERE participant_id=?", (participant_id,))
        db.executemany("INSERT INTO votes(participant_id,destination_id,tokens) VALUES (?,?,?)",
                       [(participant_id, d, n) for d, n in allocation.items()])

st.title("🌏 Group Trip Voting")
st.caption("Every participant must allocate their full budget. A destination may receive 0 tokens, or a positive amount within its per-person limits.")

if "role" not in st.session_state:
    st.session_state.role = None

with st.sidebar:
    st.header("Access")
    if st.session_state.role:
        st.write("Signed in as", st.session_state.get("display_name", "Admin"))
        if st.button("Log out"):
            for key in ("role", "participant_id", "display_name"):
                st.session_state.pop(key, None)
            st.rerun()
    else:
        tab_friend, tab_admin = st.tabs(["Friend", "Admin"])
        with tab_friend:
            people = get_people()
            if people:
                with st.form("friend_login"):
                    pid = st.selectbox("Your name", options=[p["id"] for p in people],
                                       format_func=lambda x: next(p["name"] for p in people if p["id"] == x))
                    pin = st.text_input("Your private PIN", type="password")
                    login = st.form_submit_button("Sign in")
                if login:
                    record = rows("SELECT * FROM participants WHERE id=?", (pid,))[0]
                    if verify_pin(pin, record["pin_hash"]):
                        st.session_state.role = "friend"
                        st.session_state.participant_id = pid
                        st.session_state.display_name = record["name"]
                        st.rerun()
                    else:
                        st.error("Incorrect PIN")
            else:
                st.info("Ask the organiser to add participants first.")
        with tab_admin:
            with st.form("admin_login"):
                password = st.text_input("Admin password", type="password")
                submitted = st.form_submit_button("Admin sign in")
            if submitted:
                secret = admin_secret()
                if secret and hmac.compare_digest(password, secret):
                    st.session_state.role = "admin"
                    st.session_state.display_name = "Admin"
                    st.rerun()
                else:
                    st.error("Incorrect password or ADMIN_PASSWORD not configured")

if st.session_state.role == "admin":
    st.subheader("⚙️ Admin settings")
    rules = shared_rules()
    st.markdown("**Shared voting rules**")
    st.caption("These values apply to every existing and new participant and destination. Changing rules may require participants to resubmit their votes.")
    with st.form("shared_rules"):
        budget = st.number_input("Token budget for every participant", min_value=0, value=rules["shared_budget"], step=10)
        minimum = st.number_input("Minimum tokens for every destination when selected", min_value=0, value=rules["shared_minimum"], step=10)
        maximum = st.number_input("Maximum tokens for every destination", min_value=0, value=rules["shared_maximum"], step=10)
        if st.form_submit_button("Save shared rules"):
            try:
                save_shared_rules(int(budget), int(minimum), int(maximum))
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    t_people, t_dest, t_control = st.tabs(["Participants", "Destinations", "Voting controls"])
    with t_people:
        st.dataframe(pd.DataFrame(get_people()), hide_index=True, use_container_width=True)
        with st.form("add_person"):
            name = st.text_input("Participant name")
            pin = st.text_input("Participant PIN (at least 6 characters)", type="password")
            if st.form_submit_button("Add participant"):
                if not name.strip() or len(pin) < 6:
                    st.error("Enter a name and PIN of at least 6 characters.")
                else:
                    try:
                        with connect() as db:
                            db.execute("INSERT INTO participants(name,pin_hash,budget) VALUES (?,?,(SELECT value FROM settings WHERE key='shared_budget'))",
                                       (name.strip(), hash_pin(pin)))
                        st.success("Participant added")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Participant name already exists")
        people = get_people()
        if people:
            st.markdown("**Edit an existing participant**")
            chosen = st.selectbox("Participant", [p["id"] for p in people], format_func=lambda x: next(p["name"] for p in people if p["id"] == x))
            existing = next(p for p in people if p["id"] == chosen)
            with st.form("edit_person"):
                new_pin = st.text_input("New PIN (leave blank to keep current)", type="password")
                if st.form_submit_button("Save participant"):
                    if new_pin and len(new_pin) < 6:
                        st.error("New PIN must have at least 6 characters")
                    else:
                        with connect() as db:
                            if new_pin:
                                db.execute("UPDATE participants SET pin_hash=? WHERE id=?", (hash_pin(new_pin), chosen))
                        st.success("Participant updated.")
                        st.rerun()
            with st.form(f"delete_person_{chosen}"):
                st.warning(f"Deleting {existing['name']} permanently removes this participant and all their votes.")
                confirmed = st.checkbox("Confirm participant deletion")
                if st.form_submit_button("Delete participant"):
                    if not confirmed:
                        st.error("Confirm deletion first.")
                    else:
                        with connect() as db:
                            db.execute("DELETE FROM participants WHERE id=?", (chosen,))
                        st.rerun()
    with t_dest:
        st.dataframe(pd.DataFrame(get_destinations()), hide_index=True, use_container_width=True)
        with st.form("add_destination"):
            name = st.text_input("Destination name")
            if st.form_submit_button("Add destination"):
                if not name.strip():
                    st.error("Enter a name and ensure minimum ≤ maximum")
                else:
                    try:
                        with connect() as db:
                            db.execute("""INSERT INTO destinations(name,min_tokens,max_tokens) VALUES (?,
                                       (SELECT value FROM settings WHERE key='shared_minimum'),
                                       (SELECT value FROM settings WHERE key='shared_maximum'))""", (name.strip(),))
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Destination already exists")
        destinations = get_destinations()
        if destinations:
            st.markdown("**Delete an existing destination**")
            did = st.selectbox("Destination", [d["id"] for d in destinations], format_func=lambda x: next(d["name"] for d in destinations if d["id"] == x))
            current = next(d for d in destinations if d["id"] == did)
            with st.form(f"delete_destination_{did}"):
                st.warning(
                    f"Deleting {current['name']} permanently removes this destination and its votes. "
                    "Affected participants must reallocate their tokens and resubmit their votes."
                )
                confirmed = st.checkbox("Confirm destination deletion")
                if st.form_submit_button("Delete destination"):
                    if not confirmed:
                        st.error("Confirm deletion first.")
                    else:
                        with connect() as db:
                            db.execute("DELETE FROM destinations WHERE id=?", (did,))
                        st.rerun()
    with t_control:
        open_now = st.toggle("Voting open", value=setting("voting_open"))
        show_now = st.toggle("Show leaderboard to participants", value=setting("show_results"))
        if st.button("Save voting controls"):
            set_setting("voting_open", open_now)
            set_setting("show_results", show_now)
            st.success("Saved")
        st.info("For consistent results, close voting before changing participant budgets or destination limits.")

if st.session_state.role == "friend":
    pid = st.session_state.participant_id
    matches = rows("SELECT id,name,budget FROM participants WHERE id=?", (pid,))
    if not matches:
        st.error("Your participant record has been removed. Log out and contact the organiser.")
        st.stop()
    person = matches[0]
    destinations = get_destinations()
    st.subheader(f"🗳️ Vote — {person['name']}")
    st.metric("Your token budget", person["budget"])
    if not destinations:
        st.info("No destinations have been added yet.")
    elif not setting("voting_open"):
        st.info("Voting is currently closed.")
    else:
        existing = {v["destination_id"]: v["tokens"] for v in rows("SELECT destination_id,tokens FROM votes WHERE participant_id=?", (pid,))}
        st.caption("Set 0 to skip a destination. Limits below are saved by the admin. Use +/? for steps of 10, or type an exact amount and press Enter or click outside the field to update the total.")
        if st.button("Refresh destination limits"):
            st.rerun()
        allocation = {}
        for d in destinations:
            # Include saved limits in the key so admin edits reset stale widgets.
            key = f"vote_{pid}_{d['id']}_{d['min_tokens']}_{d['max_tokens']}_{person['budget']}"
            default = existing.get(d["id"], 0)
            allocation[d["id"]] = st.number_input(
                f"{d['name']} ? minimum {d['min_tokens']}, maximum {d['max_tokens']} tokens (or 0 to skip)",
                min_value=0, max_value=d["max_tokens"],
                value=min(default, d["max_tokens"]),
                step=10, key=key)
        total = sum(allocation.values())
        st.write(f"**Allocated: {total} / {person['budget']}**")
        problem = validate(allocation, person["budget"], destinations)
        if problem:
            st.warning(problem)
        if st.button("Save / replace my votes", disabled=bool(problem)):
            try:
                save_votes(pid, allocation)
                st.success("Your votes were saved. You can edit them until voting closes.")
            except (ValueError, sqlite3.Error) as exc:
                st.error(str(exc))

if st.session_state.role == "admin" or (st.session_state.role == "friend" and setting("show_results")):
    st.subheader("🏆 Destination leaderboard")
    ranking = rows("""
        SELECT d.name, COALESCE(SUM(v.tokens),0) AS tokens,
               COUNT(CASE WHEN v.tokens > 0 THEN 1 END) AS supporters
        FROM destinations d LEFT JOIN votes v ON d.id=v.destination_id
        GROUP BY d.id ORDER BY tokens DESC, supporters DESC, d.name
    """)
    if ranking:
        st.dataframe(pd.DataFrame(ranking), hide_index=True, use_container_width=True)
        if sum(d["tokens"] for d in ranking) > 0:
            chart_data = pd.DataFrame(ranking)
            chart_data["share"] = chart_data["tokens"] / chart_data["tokens"].sum()
            pie = alt.Chart(chart_data).mark_arc().encode(
                theta=alt.Theta("tokens:Q", stack=True),
                color=alt.Color("name:N", title="Destination",
                                scale=alt.Scale(scheme="tableau20")),
                tooltip=[alt.Tooltip("name:N", title="Destination"),
                         alt.Tooltip("tokens:Q", title="Tokens"),
                         alt.Tooltip("share:Q", title="Share", format=".1%")],
            )
            st.altair_chart(pie, use_container_width=True)
        else:
            st.info("The pie chart will appear once participants allocate tokens.")
        if st.button("Refresh leaderboard"):
            st.rerun()
    else:
        st.info("Add destinations to see a leaderboard.")

if st.session_state.role is None:
    st.info("Sign in using the sidebar. The organiser should configure the admin password before starting.")
