"""Small-club SQLite store. One uvicorn worker / one scheduled sync process."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB = os.getenv("DATABASE_PATH", "./rollu.sqlite3")


def connect():
    path = Path(os.getenv("DATABASE_PATH", DB))
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=20000")
    return con


@contextmanager
def session():
    con = connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    with session() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS members(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT NOT NULL,
            game_name TEXT NOT NULL,
            tag_line TEXT NOT NULL,
            puuid TEXT NOT NULL UNIQUE,
            joined_at INTEGER NOT NULL,
            approved INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            left_at INTEGER,
            consent_public INTEGER NOT NULL DEFAULT 1,
            consent_custom INTEGER NOT NULL DEFAULT 0,
            access_token_hash TEXT NOT NULL,
            last_sync_at INTEGER,
            first_sync_at INTEGER,
            last_sync_error TEXT
        );
        CREATE TABLE IF NOT EXISTS matches(
            match_id TEXT PRIMARY KEY,
            queue_id INTEGER NOT NULL,
            played_at INTEGER NOT NULL,
            duration_sec INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS match_players(
            match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            puuid TEXT NOT NULL,
            team_id INTEGER,
            win INTEGER NOT NULL,
            kills INTEGER NOT NULL DEFAULT 0,
            deaths INTEGER NOT NULL DEFAULT 0,
            assists INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(match_id, puuid)
        );
        CREATE INDEX IF NOT EXISTS idx_matches_played_at ON matches(played_at);
        CREATE INDEX IF NOT EXISTS idx_match_players_puuid ON match_players(puuid);
        CREATE TABLE IF NOT EXISTS admin_sessions(
            token_hash TEXT PRIMARY KEY,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS viewer_sessions(
            token_hash TEXT PRIMARY KEY,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sync_status(
            id INTEGER PRIMARY KEY CHECK(id=1),
            last_started INTEGER,
            last_finished INTEGER,
            last_error TEXT,
            running INTEGER NOT NULL DEFAULT 0,
            imported_matches INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO sync_status(id, running, imported_matches) VALUES(1,0,0);
        """)
        # Existing installs: additive migration (keep all previous match and member data).
        present = {r["name"] for r in c.execute("PRAGMA table_info(members)")}
        if "active" not in present:
            c.execute("ALTER TABLE members ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        if "left_at" not in present:
            c.execute("ALTER TABLE members ADD COLUMN left_at INTEGER")
