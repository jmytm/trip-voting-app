"""SQLite storage for a local/single-server prototype."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

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
        INSERT OR IGNORE INTO settings VALUES ('voting_open','true');
        INSERT OR IGNORE INTO settings VALUES ('show_results','true');
        """)
        # Migrate existing trips using the first entry's values as shared rules.
        db.execute("BEGIN IMMEDIATE")
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
        "SELECT key,value FROM settings WHERE key IN ('shared_budget','shared_minimum','shared_maximum')")}


def save_shared_rules(budget, minimum, maximum):
    if budget < 0 or minimum < 0 or maximum < minimum:
        raise ValueError("Use nonnegative values and ensure minimum does not exceed maximum.")
    with connect() as db:
        db.executemany("UPDATE settings SET value=? WHERE key=?", [
            (str(budget), 'shared_budget'), (str(minimum), 'shared_minimum'),
            (str(maximum), 'shared_maximum')])
        db.execute("UPDATE participants SET budget=?", (budget,))
        db.execute("UPDATE destinations SET min_tokens=?,max_tokens=?", (minimum, maximum))

def rows(sql, params=()):
    with connect() as db:
        return [dict(x) for x in db.execute(sql, params).fetchall()]

def setting(key):
    result = rows("SELECT value FROM settings WHERE key=?", (key,))
    return result[0]["value"] == "true" if result else False

def set_setting(key, value):
    with connect() as db:
        db.execute("UPDATE settings SET value=? WHERE key=?", ("true" if value else "false", key))
