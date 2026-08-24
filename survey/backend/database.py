from pathlib import Path
import sqlite3


DATABASE_PATH = Path(__file__).with_name("survey.db")


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                participant_id TEXT NOT NULL,
                study_id TEXT NOT NULL,
                trial_order TEXT NOT NULL,
                current_index INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS responses (
                response_id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                trial_id INTEGER NOT NULL,
                sample_id TEXT NOT NULL,
                trial_order INTEGER NOT NULL,
                issue_type TEXT NOT NULL,
                quality_rating INTEGER NOT NULL,
                comment TEXT NOT NULL DEFAULT '',
                play_count INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                UNIQUE(session_id, trial_id)
            );
            """
        )