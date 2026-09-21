import aiosqlite
import time

DB_PATH = "shyni.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_key TEXT NOT NULL,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
  chat_key TEXT PRIMARY KEY,
  summary TEXT DEFAULT ''
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()

def make_key(chat_id: int, user_id: int, is_group: bool) -> str:
    # В ЛС память на юзера, в группе на пару чат+юзер чтобы не мешались
    return f"{chat_id}:{user_id}" if is_group else f"dm:{user_id}"

async def add_msg(chat_key: str, role: str, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (chat_key, role, text, ts) VALUES (?, ?, ?, ?)",
            (chat_key, role, text[:2000], time.time()),
        )
        # режем короткую память до 20
        await db.execute(
            "DELETE FROM messages WHERE id NOT IN "
            "(SELECT id FROM messages WHERE chat_key=? ORDER BY id DESC LIMIT 20) "
            "AND chat_key=?",
            (chat_key, chat_key),
        )
        await db.commit()

async def get_history(chat_key: str, limit: int = 12):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT role, text FROM messages WHERE chat_key=? ORDER BY id DESC LIMIT ?",
            (chat_key, limit),
        )
        rows = await cur.fetchall()
    return list(reversed(rows))

async def get_profile(chat_key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT summary FROM profiles WHERE chat_key=?", (chat_key,))
        row = await cur.fetchone()
    return row[0] if row else ""
