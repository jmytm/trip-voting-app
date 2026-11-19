"""Trip voting: run with `python -m streamlit run app.py`."""
import html
import hashlib
import hmac
import importlib
import os
import secrets
import sqlite3
import streamlit as st
import pandas as pd
import altair as alt
import card_images as image_discovery
import db as storage
import visuals

# Streamlit reruns this script but can retain imported helpers from an older version.
importlib.reload(image_discovery)
importlib.reload(storage)
importlib.reload(visuals)
from db import initialize, connect, rows, setting, set_setting, shared_rules, save_shared_rules, poll_details, save_poll_details, clear_completed_voting, validate_card_urls, save_card_details

st.set_page_config(page_title="Group Voting", page_icon="🌏", layout="wide")
st.markdown("""<style>
[data-testid="stAppViewContainer"] {background: #FAFAF9; color: #374151;}
[data-testid="stSidebar"] {background: #F1F3F4;}
[data-testid="stCaptionContainer"] {color: #737B86;}
[data-testid="stVerticalBlockBorderWrapper"] {border-color: #DFE3E8; box-shadow: none;}
.stButton > button, .stLinkButton > a {border-color: #DFE3E8; box-shadow: none;}
[data-testid="stMarkdownContainer"] h3 {font-size: 1.15rem; font-weight: 600;}
</style>""", unsafe_allow_html=True)
initialize()
poll = poll_details()
if poll.get("voting_layout") not in ("cards", "percentages"):
    poll["voting_layout"] = "percentages"
option_label = poll["option_label"]

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
    return rows("SELECT id, name, min_tokens, max_tokens, image_url, link_url FROM destinations ORDER BY name")


def card_preview(scope, image_url, link_url, requested):
    """Keep the approved image tied to the exact URLs being edited."""
    signature = (image_url.strip(), link_url.strip())
    state_key = f"card_preview_{scope}"
    if requested:
        try:
            validate_card_urls(*signature)
            with st.spinner("Finding card image..."):
                selected = signature[0] or storage.discover_card_image(signature[1])
            st.session_state[state_key] = (signature, selected)
        except ValueError as exc:
            st.session_state.pop(state_key, None)
            st.error(str(exc))
    preview = st.session_state.get(state_key)
    if not preview or preview[0] != signature:
        if any(signature):
            st.caption("Click Preview card image before saving. Preview again after changing either URL.")
        return None
    selected = preview[1]
    if selected:
        st.caption("Selected card image")
        source = html.escape(selected, quote=True)
        st.markdown(f'<img src="{source}" alt="Card image preview" style="max-width:100%;max-height:240px;object-fit:contain;">', unsafe_allow_html=True)
        st.caption("Not the image you want? Enter a direct image URL and preview again.")
    else:
        st.info("No suitable image found. You can save with a link button, or enter an image URL and preview again.")
    return selected


def has_voted(participant_id):
    return bool(rows("SELECT 1 FROM vote_submissions WHERE participant_id=?", (participant_id,)))

def validate(allocation, budget, destinations):
    if sum(allocation.values()) != budget:
        return f"Allocate exactly {budget} tokens (currently {sum(allocation.values())})."
    for d in destinations:
        amount = allocation.get(d["id"], 0)
        if not d["min_tokens"] <= amount <= d["max_tokens"]:
            return f"{d['name']}: allocate between {d['min_tokens']} and {d['max_tokens']} tokens."
    return None

def save_votes(participant_id, allocation, round_id):
    # Recheck inside one write transaction so admin changes and voting cannot race.
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT value FROM settings WHERE key='voting_open'").fetchone()[0] != "true":
            raise ValueError("Voting is closed.")
        if db.execute("SELECT value FROM settings WHERE key='round_id'").fetchone()[0] != round_id:
            raise ValueError("A new voting round has started. Reload the page before voting.")
        person = db.execute("SELECT budget FROM participants WHERE id=?", (participant_id,)).fetchone()
        if person is None:
            raise ValueError("Participant no longer exists.")
        allow_changes = db.execute("SELECT value FROM settings WHERE key='allow_vote_changes'").fetchone()[0] == "true"
        if not allow_changes and db.execute(
            "SELECT 1 FROM vote_submissions WHERE participant_id=?", (participant_id,)
        ).fetchone():
            raise ValueError("You have already voted. The admin has disabled vote changes.")
        destinations = [dict(r) for r in db.execute("SELECT * FROM destinations")]
        if set(allocation) != {d["id"] for d in destinations}:
            raise ValueError("Option list changed. Reload the page.")
        problem = validate(allocation, person["budget"], destinations)
        if problem:
            raise ValueError(problem)
        db.execute("DELETE FROM votes WHERE participant_id=?", (participant_id,))
        db.executemany("INSERT INTO votes(participant_id,destination_id,tokens) VALUES (?,?,?)",
                       [(participant_id, d, n) for d, n in allocation.items()])
        db.execute("INSERT OR IGNORE INTO vote_submissions(participant_id) VALUES (?)", (participant_id,))

st.title(f"🌏 {poll['poll_title']}")
st.caption("Every participant must allocate their full budget. Every option must receive an amount within its per-person minimum and maximum limits.")

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
    # Reset successful additions before their input widgets are recreated.
    if "participant_added" in st.session_state:
        st.session_state["new_participant_name"] = ""
        st.session_state["new_participant_pin"] = ""
    if "option_added" in st.session_state:
        for field in ("new_option_name", "new_option_image", "new_option_link"):
            st.session_state[field] = ""
        st.session_state.pop("card_preview_new", None)
    st.subheader("⚙️ Admin settings")
    with st.form("poll_details"):
        title = st.text_input("Voting title", value=poll["poll_title"], help="For example: Holiday dates or Accommodation choice")
        label = st.text_input("Option label (singular)", value=option_label, help="For example: Destination, Date range, or Accommodation")
        layouts = {"cards": "Destination / item cards with allocation controls", "percentages": "Percentages with visual distribution bar"}
        layout = st.selectbox("User voting layout", options=list(layouts),
                              index=list(layouts).index(poll["voting_layout"]),
                              format_func=layouts.get)
        if st.form_submit_button("Save voting details"):
            try:
                save_poll_details(title, label, layout)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    rules = shared_rules()
    st.markdown("**Shared voting rules**")
    st.caption("These values apply to every existing and new participant and option. Changing rules may require participants to resubmit their votes.")
    with st.form("shared_rules"):
        budget = st.number_input("Token budget for every participant", min_value=0, value=rules["shared_budget"], step=5)
        minimum = st.number_input("Minimum tokens for every option", min_value=0, value=rules["shared_minimum"], step=5)
        maximum = st.number_input("Maximum tokens for every option", min_value=0, value=rules["shared_maximum"], step=5)
        if st.form_submit_button("Save shared rules"):
            try:
                save_shared_rules(int(budget), int(minimum), int(maximum))
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    t_people, t_dest, t_control = st.tabs(["Participants", "Voting options", "Voting controls"])
    with t_people:
        if "participant_added" in st.session_state:
            st.success(st.session_state.pop("participant_added"))
        st.dataframe(pd.DataFrame(get_people()), hide_index=True, use_container_width=True)
        with st.form("add_person"):
            name = st.text_input("Participant name", key="new_participant_name")
            pin = st.text_input("Participant PIN (at least 6 characters)", type="password", key="new_participant_pin")
            if st.form_submit_button("Add participant"):
                if not name.strip() or len(pin) < 6:
                    st.error("Enter a name and PIN of at least 6 characters.")
                else:
                    try:
                        with connect() as db:
                            db.execute("INSERT INTO participants(name,pin_hash,budget) VALUES (?,?,(SELECT value FROM settings WHERE key='shared_budget'))",
                                       (name.strip(), hash_pin(pin)))
                        st.session_state["participant_added"] = f"Participant {name.strip()} has been added."
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
        if "option_added" in st.session_state:
            st.success(st.session_state.pop("option_added"))
        st.dataframe(pd.DataFrame(get_destinations()), hide_index=True, use_container_width=True)
        with st.form("add_destination"):
            name = st.text_input(f"{option_label} name", key="new_option_name")
            link_url = st.text_input("Card click-through URL (optional)", key="new_option_link", help="The page opened when someone clicks the card image. If blank, the image opens at its original URL.")
            image_url = st.text_input("Card image URL (optional)", key="new_option_image", help="Leave blank to find a social preview or content image from the click-through URL, or enter a direct image URL to choose your own.")
            preview_requested = st.form_submit_button("Preview card image", key="preview_new_card")
            add_requested = st.form_submit_button(f"Add {option_label.lower()}")
            selected_image = card_preview("new", image_url, link_url, preview_requested)
            if add_requested:
                if not name.strip():
                    st.error("Enter a name and ensure minimum ≤ maximum")
                else:
                    try:
                        validate_card_urls(image_url, link_url)
                        if (image_url.strip() or link_url.strip()) and selected_image is None:
                            raise ValueError("Preview the card image before adding this item.")
                        image_url = selected_image or ""
                        with connect() as db:
                            db.execute("""INSERT INTO destinations(name,image_url,link_url,min_tokens,max_tokens) VALUES (?,?,?,
                                       (SELECT value FROM settings WHERE key='shared_minimum'),
                                       (SELECT value FROM settings WHERE key='shared_maximum'))""", (name.strip(), image_url.strip(), link_url.strip()))
                        st.session_state["option_added"] = f"{option_label} {name.strip()} has been added."
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error(f"{option_label} already exists")
                    except ValueError as exc:
                        st.error(str(exc))
        destinations = get_destinations()
        if destinations:
            st.markdown("**Edit card details or delete an existing option**")
            did = st.selectbox(option_label, [d["id"] for d in destinations], format_func=lambda x: next(d["name"] for d in destinations if d["id"] == x))
            current = next(d for d in destinations if d["id"] == did)
            with st.form(f"edit_card_{did}"):
                edited_link = st.text_input("Card click-through URL", value=current["link_url"])
                edited_image = st.text_input("Card image URL (optional)", value=current["image_url"], help="Clear this field to find a social preview or content image from the click-through URL when saving.")
                preview_requested = st.form_submit_button("Preview card image", key=f"preview_card_{did}")
                save_requested = st.form_submit_button("Save card details")
                selected_image = card_preview(f"edit_{did}", edited_image, edited_link, preview_requested)
                if save_requested:
                    try:
                        validate_card_urls(edited_image, edited_link)
                        if (edited_image.strip() or edited_link.strip()) and selected_image is None:
                            raise ValueError("Preview the card image before saving these details.")
                        save_card_details(did, selected_image or "", edited_link, auto_discover=False)
                        st.success("Card details saved.")
                    except ValueError as exc:
                        st.error(str(exc))
            with st.form(f"delete_destination_{did}"):
                st.warning(
                    f"Deleting {current['name']} permanently removes this option and its votes. "
                    "Affected participants must reallocate their tokens and resubmit their votes."
                )
                confirmed = st.checkbox("Confirm option deletion")
                if st.form_submit_button(f"Delete {option_label.lower()}"):
                    if not confirmed:
                        st.error("Confirm deletion first.")
                    else:
                        with connect() as db:
                            db.execute("DELETE FROM destinations WHERE id=?", (did,))
                        st.rerun()
    with t_control:
        open_now = st.toggle("Voting open", value=setting("voting_open"))
        show_now = st.toggle("Show leaderboard to participants", value=setting("show_results"))
        st.caption("Participants can see the leaderboard and pie chart only after submitting their votes.")
        allow_changes = st.toggle("Allow participants to change their votes", value=setting("allow_vote_changes"))
        st.caption("When disabled, each participant can submit only once. Enable this again to allow corrections after rule or option changes.")
        if st.button("Save voting controls"):
            set_setting("voting_open", open_now)
            set_setting("show_results", show_now)
            set_setting("allow_vote_changes", allow_changes)
            st.success("Saved")
        st.info("For consistent results, close voting before changing participant budgets or option limits.")

        st.markdown("**Delete completed voting**")
        with st.form("clear_completed_voting"):
            st.warning("Permanently delete all votes and results for this round. Participants and PINs are kept. Close voting first; reopen it when the next round is ready.")
            delete_options = st.checkbox("Also delete all voting options")
            confirmed = st.checkbox("Confirm deletion of completed voting")
            if st.form_submit_button("Delete completed voting"):
                if not confirmed:
                    st.error("Confirm deletion first.")
                else:
                    try:
                        clear_completed_voting(delete_options)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

if st.session_state.role == "friend":
    pid = st.session_state.participant_id
    matches = rows("SELECT id,name,budget FROM participants WHERE id=?", (pid,))
    if not matches:
        st.error("Your participant record has been removed. Log out and contact the organiser.")
        st.stop()
    person = matches[0]
    voted = has_voted(pid)
    destinations = get_destinations()
    st.subheader(f"🗳️ Vote — {person['name']}")
    st.metric("Your token budget", person["budget"])
    if not destinations:
        st.info("No voting options have been added yet.")
    elif not setting("voting_open"):
        st.info("Voting is currently closed.")
    elif voted and not setting("allow_vote_changes"):
        st.info("Your vote has been submitted. The admin has limited voting to one submission per participant.")
    else:
        existing = {v["destination_id"]: v["tokens"] for v in rows("SELECT destination_id,tokens FROM votes WHERE participant_id=?", (pid,))}
        layout = poll["voting_layout"]
        if layout == "percentages":
            st.caption("Allocate tokens to every option within the admin's limits. The bar and percentages below update to show your distribution. Use the plus and minus buttons for steps of 5, or type an exact amount.")
        else:
            st.caption("Allocate tokens to every option within the limits set by the admin. Use the plus and minus buttons for steps of 5, or type an exact amount and press Enter or click outside the field to update the total.")
        st.caption(f"For every item: minimum {destinations[0]['min_tokens']}, maximum {destinations[0]['max_tokens']} tokens.")
        allocation = {}
        distribution_view = st.empty() if layout == "percentages" else None
        columns = st.columns(2) if layout == "cards" else None
        for index, d in enumerate(destinations):
            # Include the layout and rules so changed settings reset stale widgets.
            key = f"vote_{poll['round_id']}_{pid}_{d['id']}_{d['min_tokens']}_{d['max_tokens']}_{person['budget']}_{layout}"
            default = max(d["min_tokens"], min(existing.get(d["id"], d["min_tokens"]), d["max_tokens"]))
            container = columns[index % 2].container(border=True) if columns else st.container()
            with container:
                if layout == "cards":
                    st.markdown("### " + d["name"], unsafe_allow_html=False)
                    if d["image_url"]:
                        image = html.escape(d["image_url"], quote=True)
                        target = html.escape(d["link_url"] or d["image_url"], quote=True)
                        title = html.escape(d["name"], quote=True)
                        st.markdown(f'<a href="{target}" target="_blank" rel="noopener noreferrer"><img src="{image}" alt="{title}" style="width:100%;height:200px;object-fit:cover;border-radius:8px;"></a>', unsafe_allow_html=True)
                    elif d["link_url"]:
                        st.link_button("View item", d["link_url"])
                allocation[d["id"]] = st.number_input(
                    d["name"],
                    min_value=d["min_tokens"], max_value=d["max_tokens"],
                    value=default, step=5, key=key)
                if layout == "percentages":
                    percentage = 100 * allocation[d["id"]] / person["budget"] if person["budget"] else 0
                    st.caption(f"{percentage:.2f}% of your token budget")
        if layout == "percentages" and person["budget"] > 0:
            distribution = [{"item": d["name"], "tokens": allocation[d["id"]],
                             "percentage": allocation[d["id"]] / person["budget"]}
                            for d in destinations]
            remaining = max(0, person["budget"] - sum(allocation.values()))
            if remaining:
                distribution.append({"item": "Unallocated", "tokens": remaining,
                                     "percentage": remaining / person["budget"]})
            offset = 0.0
            for index, segment in enumerate(distribution):
                segment["start"] = offset
                offset += segment["percentage"]
                segment["end"] = offset
                segment["midpoint"] = (segment["start"] + segment["end"]) / 2
                segment["label"] = str(segment["tokens"])
                segment["show_label"] = segment["percentage"] / max(1, sum(allocation.values()) / person["budget"]) >= max(0.035, len(segment["label"]) * 0.009)
            colors = visuals.item_colors([d["name"] for d in destinations])
            if remaining:
                colors["Unallocated"] = visuals.UNALLOCATED
            chart_data = pd.DataFrame(distribution)
            base = alt.Chart(chart_data)
            scale = alt.Scale(domain=[0, max(1, offset)])
            hover_details = [alt.Tooltip("item:N", title="Item"),
                             alt.Tooltip("tokens:Q", title="Tokens"),
                             alt.Tooltip("percentage:Q", title="Percentage", format=".2%")]
            bar = base.mark_bar(stroke="#FAFAF9", strokeWidth=2).encode(
                x=alt.X("start:Q", title=None, axis=None, scale=scale),
                x2="end:Q", color=alt.Color("item:N", title="Item", scale=visuals.color_scale(colors), legend=None),
                tooltip=hover_details)
            label_data = base.transform_filter(alt.datum.show_label)
            names = label_data.mark_text(
                color="white", fontWeight="bold", fontSize=12, dy=-11,
                limit=alt.ExprRef(expr=f"max(0, (datum.end - datum.start) / {max(1, offset)} * width - 10)")
            ).encode(x=alt.X("midpoint:Q", scale=scale), text="item:N", tooltip=hover_details)
            counts = label_data.mark_text(color="white", fontWeight="bold", fontSize=13, dy=12).encode(
                x=alt.X("midpoint:Q", scale=scale), text="label:N", tooltip=hover_details)
            with distribution_view.container():
                st.write(f"**Allocated: {100 * sum(allocation.values()) / person['budget']:.1f}% / 100%**")
                st.altair_chart(visuals.chart_style((bar + names + counts).properties(height=104)), use_container_width=True, theme=None)
                st.markdown(visuals.distribution_legend(distribution, colors), unsafe_allow_html=True)
                st.caption("Each segment shows the item name above its token count. Full names and counts for narrow segments are listed below.")
        total = sum(allocation.values())
        if layout != "percentages":
            st.write(f"**Allocated: {total} / {person['budget']}**")
        problem = validate(allocation, person["budget"], destinations)
        if problem:
            st.warning(problem)
        if st.button("Update my votes" if voted else "Submit my votes", disabled=bool(problem)):
            try:
                save_votes(pid, allocation, poll["round_id"])
                st.success("Your votes were saved.")
            except (ValueError, sqlite3.Error) as exc:
                st.error(str(exc))

if st.session_state.role == "friend" and setting("show_results") and not has_voted(st.session_state.participant_id):
    st.info("Submit your votes to see the leaderboard and pie chart.")

if st.session_state.role == "admin" or (st.session_state.role == "friend" and setting("show_results") and has_voted(st.session_state.participant_id)):
    st.subheader(f"{poll['poll_title']} results")
    ranking = rows("""
        SELECT d.name AS item, COALESCE(SUM(v.tokens),0) AS total,
               COUNT(CASE WHEN v.tokens > 0 THEN 1 END) AS supporters
        FROM destinations d LEFT JOIN votes v ON d.id=v.destination_id
        GROUP BY d.id ORDER BY total DESC, supporters DESC, d.name
    """)
    if ranking:
        st.dataframe(pd.DataFrame(ranking), hide_index=True, use_container_width=True)
        if sum(d["total"] for d in ranking) > 0:
            chart_data = pd.DataFrame(ranking)
            chart_data["share"] = chart_data["total"] / chart_data["total"].sum()
            colors = visuals.item_colors([d["name"] for d in get_destinations()])
            pie = alt.Chart(chart_data).mark_arc(stroke="#FAFAF9", strokeWidth=2).encode(
                theta=alt.Theta("total:Q", stack=True, title="Total"),
                color=alt.Color("item:N", title="Item",
                                scale=visuals.color_scale(colors)),
                tooltip=[alt.Tooltip("item:N", title="Item"),
                         alt.Tooltip("total:Q", title="Total"),
                         alt.Tooltip("share:Q", title="Share", format=".1%")],
            )
            st.altair_chart(visuals.chart_style(pie).properties(height=280), use_container_width=True, theme=None)
        else:
            st.info("The pie chart will appear once participants allocate tokens.")
        if st.button("Refresh leaderboard"):
            st.rerun()
    else:
        st.info("Add voting options to see a leaderboard.")

if st.session_state.role is None:
    st.info("Sign in using the sidebar. The organiser should configure the admin password before starting.")
