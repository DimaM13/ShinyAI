import asyncio
import os
import tempfile
import time
import traceback
import warnings
warnings.filterwarnings("ignore")

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from dotenv import load_dotenv

load_dotenv()
import config
import memory
import brain
import tts_voice
import settings

def log(msg: str):
    safe = str(msg).encode("cp1251", "backslashreplace").decode("cp1251")
    print(f"[{time.strftime('%H:%M:%S')}] {safe}", flush=True)

bot = Bot(token=config.TELEGRAM_TOKEN)
dp = Dispatcher()

BOT_ID = 0
BOT_USERNAME = ""

def is_owner(u) -> bool:
    return bool(u) and u.id == config.OWNER_ID

def _owner_cb(cb: CallbackQuery) -> bool:
    return is_owner(cb.from_user)

# ---------- клавиатуры ----------

def kb_voices() -> InlineKeyboardMarkup:
    active = settings.get_base_voice()
    rows = []
    for (name,) in settings.list_base_voices():
        mark = "✅ " if name == active else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"m:bv:{name}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def menu_text() -> str:
    return f"🎛 Shyni: голос\nТекущее: {tts_voice.current_status()}"

# ---------- настройки ----------

@dp.message(Command("settings"))
async def cmd_settings(m: Message):
    if not is_owner(m.from_user):
        return
    await m.answer(menu_text(), reply_markup=kb_voices())

@dp.callback_query(F.data.startswith("m:bv:"))
async def cb_base_voice(cb: CallbackQuery):
    if not _owner_cb(cb):
        await cb.answer("Не твои кнопки 🙂")
        return
    name = cb.data[len("m:bv:"):]
    if settings.get_base_voice_row(name) is None:
        await cb.answer("Такого голоса нет")
        return
    settings.set_base_voice(name)
    # сброс кэша промпта чтобы подхватился новый голос без перезапуска
    tts_voice._clone_prompts.pop(name, None)
    log(f"голос base -> {name}")
    await cb.message.edit_text(menu_text(), reply_markup=kb_voices())
    await cb.answer(f"Голос: {name}")

# ---------- болталка ----------

@dp.message(F.text == "/start")
async def start(m: Message):
    log(f"/start от {m.from_user.id} в {m.chat.type}")
    await m.answer("Привет! Я Shyni. Пиши мне текстом, а я буду отвечать голосом.")

def should_reply(m: Message) -> tuple[bool, str]:
    if m.chat.type == "private":
        return True, "лс"
    if m.reply_to_message and m.reply_to_message.from_user and m.reply_to_message.from_user.id == BOT_ID:
        return True, "реплай на бота"
    txt = (m.text or "")
    low = txt.lower()
    for e in (m.entities or []):
        if e.type == "mention":
            mention = txt[e.offset:e.offset + e.length].lower()
            if BOT_USERNAME and mention == "@" + BOT_USERNAME:
                return True, "упоминание"
        elif e.type == "text_mention" and e.user and e.user.id == BOT_ID:
            return True, "упоминание"
    if BOT_USERNAME and ("@" + BOT_USERNAME) in low:
        return True, "упоминание"
    if "shyni" in low or "shiny" in low:
        return True, "упоминание"
    return False, "группа без обращения - игнор"

@dp.message(F.text)
async def on_text(m: Message):
    t_all = time.time()
    if not m.text or m.text.startswith("/"):
        return
    ok, reason = should_reply(m)
    log(f"ВХОД [{m.chat.type}] user={m.from_user.id} ({(m.from_user.username or '')}): {m.text[:100]!r} -> {reason}")
    if not ok:
        return

    is_group = m.chat.type in ("group", "supergroup")
    key = memory.make_key(m.chat.id, m.from_user.id, is_group)

    await memory.add_msg(key, "user", m.text)
    await bot.send_chat_action(m.chat.id, "record_voice")

    try:
        t0 = time.time()
        log("мозг: запрос к Gemma...")
        reply = await brain.shyni_reply(m.text, key)
        log(f"мозг: готово за {time.time()-t0:.1f}с: {reply[:120]!r}")
        await memory.add_msg(key, "assistant", reply)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tf:
            out = tf.name
        try:
            t1 = time.time()
            log("голос: синтез TTS...")
            await asyncio.to_thread(tts_voice.speak_to_ogg, reply, out)
            log(f"голос: готов за {time.time()-t1:.1f}с, отправляю... (всего {time.time()-t_all:.1f}с)")
            await m.answer_voice(FSInputFile(out))
            log("отправлено голосом, ок")
        finally:
            if os.path.exists(out):
                os.remove(out)
    except Exception as e:
        log(f"ОШИБКА обработки: {type(e).__name__}: {e}")
        traceback.print_exc()
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tf:
            out = tf.name
        try:
            await asyncio.to_thread(tts_voice.speak_to_ogg, "Ой... что-то зашипело, попробуй еще раз!", out)
            await m.answer_voice(FSInputFile(out))
        finally:
            if os.path.exists(out):
                os.remove(out)

async def main():
    global BOT_ID, BOT_USERNAME
    log("старт, init db...")
    await memory.init_db()
    await asyncio.to_thread(settings.init_settings)
    try:
        me = await bot.get_me()
        BOT_ID = me.id
        BOT_USERNAME = (me.username or "").lower()
        log(f"я @{BOT_USERNAME} id={BOT_ID}, owner={config.OWNER_ID}")
    except Exception as e:
        log(f"get_me fail: {e}")
    log("warmup TTS (клон, 1-2 мин, тихо)...")
    try:
        t0 = time.time()
        await asyncio.to_thread(tts_voice.speak_to_ogg, "Привет! Я Shyni, прогрев!", tempfile.mktemp(suffix=".ogg"))
        log(f"warmup ок за {time.time()-t0:.0f}с")
    except Exception as e:
        log(f"warmup fail: {e}")
    log("polling... пиши боту в ТГ")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
