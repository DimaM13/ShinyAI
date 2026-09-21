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
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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
dp = Dispatcher(storage=MemoryStorage())

BOT_ID = 0
BOT_USERNAME = ""

def is_owner(u) -> bool:
    return bool(u) and u.id == config.OWNER_ID

class VDNew(StatesGroup):
    name = State()
    instruct = State()

# ---------- клавиатуры ----------

def kb_menu() -> InlineKeyboardMarkup:
    mode = settings.get_mode()
    mark = lambda m: "✅ " if mode == m else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{mark('base')}🎙 Клон (Base)", callback_data="m:mode:base")],
        [InlineKeyboardButton(text=f"{mark('voicedesign')}✨ VoiceDesign", callback_data="m:mode:vd")],
        [InlineKeyboardButton(text="⚙ Настройки режима", callback_data="m:sub")],
    ])

def kb_base() -> InlineKeyboardMarkup:
    active = settings.get_base_voice()
    rows = []
    for (name,) in settings.list_base_voices():
        mark = "✅ " if name == active else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"m:bv:{name}")])
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data="m:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_vd() -> InlineKeyboardMarkup:
    active = settings.get_vd_preset()
    rows = []
    for (name,) in settings.list_vd_presets():
        mark = "✅ " if name == active else ""
        rows.append([
            InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"m:vd:{name}"),
            InlineKeyboardButton(text="❌", callback_data=f"m:vddel:{name}"),
        ])
    rows.append([InlineKeyboardButton(text="➕ Новый пресет", callback_data="m:vd:new")])
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data="m:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def menu_text() -> str:
    return f"🎛 Shyni: настройки голоса\nТекущее: {tts_voice.current_status()}"

# ---------- настройки ----------

@dp.message(Command("settings"))
async def cmd_settings(m: Message, state: FSMContext):
    if not is_owner(m.from_user):
        return
    await state.clear()
    await m.answer(menu_text(), reply_markup=kb_menu())

@dp.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    if not is_owner(m.from_user):
        return
    await state.clear()
    await m.answer("Отменено.", reply_markup=None)

def _owner_cb(cb: CallbackQuery) -> bool:
    return is_owner(cb.from_user)

@dp.callback_query(F.data == "m:menu")
async def cb_menu(cb: CallbackQuery):
    if not _owner_cb(cb):
        await cb.answer("Не твои кнопки 🙂")
        return
    await cb.message.edit_text(menu_text(), reply_markup=kb_menu())
    await cb.answer()

@dp.callback_query(F.data == "m:sub")
async def cb_sub(cb: CallbackQuery):
    if not _owner_cb(cb):
        await cb.answer("Не твои кнопки 🙂")
        return
    if settings.get_mode() == "base":
        await cb.message.edit_text(
            f"🎙 Клон (Base), голос: {settings.get_base_voice()}\nГолоса добавляются файлами, выбор тут:",
            reply_markup=kb_base(),
        )
    else:
        await cb.message.edit_text(
            f"✨ VoiceDesign, пресет: {settings.get_vd_preset()}",
            reply_markup=kb_vd(),
        )
    await cb.answer()

@dp.callback_query(F.data.startswith("m:mode:"))
async def cb_mode(cb: CallbackQuery):
    if not _owner_cb(cb):
        await cb.answer("Не твои кнопки 🙂")
        return
    mode = "voicedesign" if cb.data == "m:mode:vd" else "base"
    if settings.get_mode() == mode:
        await cb.answer("Уже этот режим")
        return
    await cb.answer("Выгружаю и гружу новый режим, 1-2 мин...")
    await cb.message.edit_text(f"⏳ Переключаю на {tts_voice.MODE_NAMES[mode]}... модель выгружается и грузится, жди.")
    try:
        settings.set_mode(mode)
        dt = await asyncio.to_thread(tts_voice.switch_mode, mode)
        log(f"режим переключен на {mode} за {dt:.0f}с")
        await cb.message.edit_text(f"✅ Готово за {dt:.0f}с: {tts_voice.current_status()}", reply_markup=kb_menu())
    except Exception as e:
        log(f"ОШИБКА смены режима: {e}")
        traceback.print_exc()
        await cb.message.edit_text(f"❌ Не взлетело: {e}", reply_markup=kb_menu())

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
    log(f"голос base -> {name}")
    await cb.message.edit_text(f"🎙 Клон (Base), голос: {name}", reply_markup=kb_base())
    await cb.answer(f"Голос: {name}")

@dp.callback_query(F.data.startswith("m:vd:") & ~F.data.in_({"m:vd:new"}))
async def cb_vd_preset(cb: CallbackQuery):
    if not _owner_cb(cb):
        await cb.answer("Не твои кнопки 🙂")
        return
    name = cb.data[len("m:vd:"):]
    if settings.get_vd_instruct(name) is None:
        await cb.answer("Такого пресета нет")
        return
    settings.set_vd_preset(name)
    log(f"пресет vd -> {name}")
    await cb.message.edit_text(f"✨ VoiceDesign, пресет: {name}", reply_markup=kb_vd())
    await cb.answer(f"Пресет: {name}")

@dp.callback_query(F.data.startswith("m:vddel:"))
async def cb_vd_del(cb: CallbackQuery):
    if not _owner_cb(cb):
        await cb.answer("Не твои кнопки 🙂")
        return
    name = cb.data[len("m:vddel:"):]
    if settings.del_vd_preset(name):
        log(f"пресет удален: {name}")
        await cb.message.edit_text(f"✨ VoiceDesign, пресет: {settings.get_vd_preset()}", reply_markup=kb_vd())
        await cb.answer(f"Удален: {name}")
    else:
        await cb.answer("Нельзя удалить последний пресет")

@dp.callback_query(F.data == "m:vd:new")
async def cb_vd_new(cb: CallbackQuery, state: FSMContext):
    if not _owner_cb(cb):
        await cb.answer("Не твои кнопки 🙂")
        return
    await state.set_state(VDNew.name)
    await cb.message.answer("Как назовем пресет? (до 20 символов, латиница/цифры)")
    await cb.answer()

@dp.message(VDNew.name)
async def vd_new_name(m: Message, state: FSMContext):
    if not is_owner(m.from_user):
        return
    name = (m.text or "").strip().lower().replace(" ", "_")[:20]
    if not name or len(name) < 2:
        await m.answer("Коротковато. Придумай название от 2 символов:")
        return
    await state.update_data(name=name)
    await state.set_state(VDNew.instruct)
    await m.answer(f"Ок, пресет `{name}`. Теперь опиши голос (это и есть instruct):\nНапример: молодая девушка, звонкий голос, говорит дерзко и весело")

@dp.message(VDNew.instruct)
async def vd_new_instruct(m: Message, state: FSMContext):
    if not is_owner(m.from_user):
        return
    data = await state.get_data()
    name = data.get("name", "new")
    instruct = (m.text or "").strip()[:500]
    if len(instruct) < 10:
        await m.answer("Слишком короткое описание. Распиши голос подробнее:")
        return
    settings.add_vd_preset(name, instruct)
    settings.set_vd_preset(name)
    await state.clear()
    log(f"новый пресет vd: {name}")
    await m.answer(f"✅ Пресет `{name}` создан и включен:\n{instruct[:200]}", reply_markup=kb_vd())

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
    log(f"warmup TTS ({settings.get_mode()}, 1-2 мин, тихо)...")
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
