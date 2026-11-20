"""SQLite storage for a local/single-server prototype."""
import os
import sqlite3
from urllib.parse import urlsplit
from contextlib import contextmanager
from pathlib import Path
from card_images import discover_card_image

DB_PATH = Path(os.environ.get("TRIP_DB_PATH", Path(__file__).parent / "trip_votes.db"))

@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=20000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def initialize():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            pin_hash TEXT NOT NULL, budget INTEGER NOT NULL CHECK(budget >= 0)
        );
        CREATE TABLE IF NOT EXISTS destinations (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            min_tokens INTEGER NOT NULL CHECK(min_tokens >= 0),
            max_tokens INTEGER NOT NULL CHECK(max_tokens >= min_tokens)
        );
        CREATE TABLE IF NOT EXISTS votes (
            participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
            destination_id INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
            tokens INTEGER NOT NULL CHECK(tokens >= 0),
            PRIMARY KEY(participant_id, destination_id)
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS vote_submissions (
            participant_id INTEGER PRIMARY KEY REFERENCES participants(id) ON DELETE CASCADE
        );
        INSERT OR IGNORE INTO vote_submissions SELECT DISTINCT participant_id FROM votes;
        INSERT OR IGNORE INTO settings VALUES ('voting_open','true');
        INSERT OR IGNORE INTO settings VALUES ('show_results','true');
        INSERT OR IGNORE INTO settings VALUES ('allow_vote_changes','true');
        INSERT OR IGNORE INTO settings VALUES ('poll_title','Group Voting');
        INSERT OR IGNORE INTO settings VALUES ('option_label','Option');
        INSERT OR IGNORE INTO settings VALUES ('round_id','1');
        INSERT OR IGNORE INTO settings VALUES ('voting_layout','percentages');
        INSERT OR IGNORE INTO settings VALUES ('vote_step','5');
        INSERT OR IGNORE INTO settings VALUES ('voting_instructions','');
        """)
        # Migrate existing trips using the first entry's values as shared rules.
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE settings SET value='percentages' WHERE key='voting_layout' AND value='simple'")
        columns = {r['name'] for r in db.execute("PRAGMA table_info(destinations)")}
        for column in ('image_url', 'link_url'):
            if column not in columns:
                db.execute(f"ALTER TABLE destinations ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        db.execute("""INSERT OR IGNORE INTO settings VALUES
                   ('shared_budget', COALESCE((SELECT budget FROM participants ORDER BY id LIMIT 1),100))""")
        db.execute("""INSERT OR IGNORE INTO settings VALUES
                   ('shared_minimum', COALESCE((SELECT min_tokens FROM destinations ORDER BY id LIMIT 1),10))""")
        db.execute("""INSERT OR IGNORE INTO settings VALUES
                   ('shared_maximum', COALESCE((SELECT max_tokens FROM destinations ORDER BY id LIMIT 1),50))""")
        db.execute("UPDATE participants SET budget=(SELECT value FROM settings WHERE key='shared_budget')")
        db.execute("""UPDATE destinations SET
                   min_tokens=(SELECT value FROM settings WHERE key='shared_minimum'),
                   max_tokens=(SELECT value FROM settings WHERE key='shared_maximum')""")


def shared_rules():
    return {r['key']: int(r['value']) for r in rows(
        "SELECT key,value FROM settings WHERE key IN ('shared_budget','shared_minimum','shared_maximum','vote_step')")}


def save_shared_rules(budget, minimum, maximum, vote_step=None):
    if budget < 0 or minimum < 0 or maximum < minimum:
        raise ValueError("Use nonnegative values and ensure minimum does not exceed maximum.")
    if vote_step is not None and (type(vote_step) is not int or vote_step < 1):
        raise ValueError("The plus/minus token step must be a whole number of at least 1.")
    with connect() as db:
        db.executemany("UPDATE settings SET value=? WHERE key=?", [
            (str(budget), 'shared_budget'), (str(minimum), 'shared_minimum'),
            (str(maximum), 'shared_maximum')])
        db.execute("UPDATE participants SET budget=?", (budget,))
        db.execute("UPDATE destinations SET min_tokens=?,max_tokens=?", (minimum, maximum))
        if vote_step is not None:
            db.execute("INSERT INTO settings(key,value) VALUES ('vote_step',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(vote_step),))

def rows(sql, params=()):
    with connect() as db:
        return [dict(x) for x in db.execute(sql, params).fetchall()]

def setting(key):
    result = rows("SELECT value FROM settings WHERE key=?", (key,))
    return result[0]["value"] == "true" if result else False

def set_setting(key, value):
    with connect() as db:
        db.execute("UPDATE settings SET value=? WHERE key=?", ("true" if value else "false", key))


def poll_details():
    details = {'voting_layout': 'percentages', 'voting_instructions': ''}
    details.update({r['key']: r['value'] for r in rows(
        "SELECT key,value FROM settings WHERE key IN ('poll_title','option_label','round_id','voting_layout','voting_instructions')")})
    return details


def validate_card_urls(image_url, link_url):
    for label, value in (("Image URL", image_url), ("Click-through URL", link_url)):
        if not value.strip():
            continue
        try:
            parsed = urlsplit(value.strip())
            valid = parsed.scheme in ('http', 'https') and bool(parsed.hostname)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(f"{label} must be a full http:// or https:// URL.")


def save_card_details(option_id, image_url, link_url, auto_discover=True):
    validate_card_urls(image_url, link_url)
    image_url = image_url.strip()
    if not image_url and auto_discover:
        image_url = discover_card_image(link_url.strip())
    with connect() as db:
        db.execute("UPDATE destinations SET image_url=?,link_url=? WHERE id=?",
                   (image_url.strip(), link_url.strip(), option_id))


def save_poll_details(title, label, layout='percentages', instructions=None):
    if not title.strip() or not label.strip():
        raise ValueError("Enter a voting title and an option label.")
    if layout not in ('cards', 'percentages'):
        raise ValueError("Choose a supported voting layout.")
    with connect() as db:
        db.executemany("INSERT INTO settings(value,key) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", [
            (title.strip(), 'poll_title'), (label.strip(), 'option_label'),
            (layout, 'voting_layout')])
        if instructions is not None:
            db.execute("INSERT INTO settings(key,value) VALUES ('voting_instructions',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (instructions.strip(),))


def leaderboard():
    """Average across submitted participants, including their zero allocations."""
    with connect() as db:
        db.execute("BEGIN")
        submitted = db.execute("SELECT COUNT(*) FROM vote_submissions").fetchone()[0]
        ranking = [dict(r) for r in db.execute("""
            SELECT d.name AS item,
                   COALESCE(SUM(v.tokens),0) * 1.0 / MAX(?,1) AS average_tokens,
                   COUNT(CASE WHEN v.tokens > 0 THEN 1 END) AS supporters
            FROM destinations d LEFT JOIN votes v ON d.id=v.destination_id
            GROUP BY d.id ORDER BY average_tokens DESC, supporters DESC, d.name
        """, (submitted,))]
    return ranking, submitted


def clear_completed_voting(delete_options=False):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT value FROM settings WHERE key='voting_open'").fetchone()[0] == 'true':
            raise ValueError("Close voting before deleting completed votes.")
        db.execute("DELETE FROM votes")
        db.execute("DELETE FROM vote_submissions")
        if delete_options:
            db.execute("DELETE FROM destinations")
        db.execute("UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='round_id'")
