"""Настройки Shyni: голоса Base для клона.

Синхронный sqlite (тот же shyni.db) - дергается и из хендлеров, и из потока синтеза.
"""
import sqlite3
import config

DB_PATH = "shyni.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS base_voices (
  name TEXT PRIMARY KEY,
  ref_audio TEXT NOT NULL,
  ref_text TEXT NOT NULL
);
"""

def _con():
    return sqlite3.connect(DB_PATH, timeout=10)

def init_settings():
    with _con() as db:
        db.executescript(SCHEMA)
        db.execute("DROP TABLE IF EXISTS vd_presets")
        db.execute("DELETE FROM kv WHERE key IN ('tts_mode', 'vd_preset')")
        db.execute("INSERT OR IGNORE INTO kv (key, value) VALUES ('base_voice', 'shyni')")
        db.execute(
            "INSERT OR IGNORE INTO base_voices (name, ref_audio, ref_text) VALUES (?, ?, ?)",
            ("shyni", config.REF_AUDIO, config.REF_TEXT),
        )

def _get(key: str, default: str = "") -> str:
    with _con() as db:
        row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row[0] if row else default

def _set(key: str, value: str):
    with _con() as db:
        db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))

def get_base_voice() -> str:
    return _get("base_voice", "shyni")

def set_base_voice(name: str):
    _set("base_voice", name)

def list_base_voices():
    with _con() as db:
        return db.execute("SELECT name FROM base_voices ORDER BY name").fetchall()

def get_base_voice_row(name: str):
    with _con() as db:
        return db.execute(
            "SELECT ref_audio, ref_text FROM base_voices WHERE name=?", (name,)
        ).fetchone()

def add_base_voice(name: str, ref_audio: str, ref_text: str):
    with _con() as db:
        db.execute(
            "INSERT OR REPLACE INTO base_voices (name, ref_audio, ref_text) VALUES (?, ?, ?)",
            (name, ref_audio, ref_text),
        )
