"""Настройки Shyni: режим TTS, голоса Base, пресеты VoiceDesign.

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
CREATE TABLE IF NOT EXISTS vd_presets (
  name TEXT PRIMARY KEY,
  instruct TEXT NOT NULL
);
"""

DEFAULT_VD_INSTRUCT = (
    "Молодая девушка, звонкий высокий голос, милая и игривая, "
    "говорит по-русски живо и эмоционально."
)

def _con():
    return sqlite3.connect(DB_PATH, timeout=10)

def init_settings():
    with _con() as db:
        db.executescript(SCHEMA)
        db.execute("INSERT OR IGNORE INTO kv (key, value) VALUES ('tts_mode', 'base')")
        db.execute("INSERT OR IGNORE INTO kv (key, value) VALUES ('base_voice', 'shyni')")
        db.execute("INSERT OR IGNORE INTO kv (key, value) VALUES ('vd_preset', 'shyni')")
        db.execute(
            "INSERT OR IGNORE INTO base_voices (name, ref_audio, ref_text) VALUES (?, ?, ?)",
            ("shyni", config.REF_AUDIO, config.REF_TEXT),
        )
        db.execute(
            "INSERT OR IGNORE INTO vd_presets (name, instruct) VALUES (?, ?)",
            ("shyni", DEFAULT_VD_INSTRUCT),
        )

def _get(key: str, default: str = "") -> str:
    with _con() as db:
        row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row[0] if row else default

def _set(key: str, value: str):
    with _con() as db:
        db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))

def get_mode() -> str:
    m = _get("tts_mode", "base")
    return m if m in ("base", "voicedesign") else "base"

def set_mode(mode: str):
    _set("tts_mode", mode)

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

def get_vd_preset() -> str:
    return _get("vd_preset", "shyni")

def set_vd_preset(name: str):
    _set("vd_preset", name)

def list_vd_presets():
    with _con() as db:
        return db.execute("SELECT name FROM vd_presets ORDER BY name").fetchall()

def get_vd_instruct(name: str):
    with _con() as db:
        row = db.execute("SELECT instruct FROM vd_presets WHERE name=?", (name,)).fetchone()
    return row[0] if row else None

def add_vd_preset(name: str, instruct: str):
    with _con() as db:
        db.execute("INSERT OR REPLACE INTO vd_presets (name, instruct) VALUES (?, ?)", (name, instruct))

def del_vd_preset(name: str) -> bool:
    """Нельзя удалить последний пресет и активный сносим на первый оставшийся."""
    names = [r[0] for r in list_vd_presets()]
    if name not in names or len(names) <= 1:
        return False
    with _con() as db:
        db.execute("DELETE FROM vd_presets WHERE name=?", (name,))
    if get_vd_preset() == name:
        set_vd_preset([n for n in names if n != name][0])
    return True
