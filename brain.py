import asyncio
import random
import time
from google import genai
from google.genai import types
import config
import memory

MAX_ATTEMPTS = 10

_client = None

def log(msg: str):
    # cp1251 тянет кириллицу, роняет только эмодзи - их экранируем, остальное читаемо
    safe = str(msg).encode("cp1251", "backslashreplace").decode("cp1251")
    print(f"[{time.strftime('%H:%M:%S')}] [brain] {safe}", flush=True)

def get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GOOGLE_API_KEY)
    return _client

def _make_config():
    return types.GenerateContentConfig(
        system_instruction=config.SHYNI_SYSTEM,
        temperature=0.7,
        max_output_tokens=500,
        # Без этого модель 40с "думает" и ответ не влезает в лимит -> пустой text
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
        # У нас нет tools - гасим AFC чтобы SDK не спамил варнингом
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

FALLBACKS = [
    "Хихи... сервак Гугла чихнул, повтори еще разок!",
    "Ой, мои мозги подвисли... скажи еще раз, пожалуйста!",
    "Бака, нейронка моя глюканула! Повтори, а?",
]

async def shyni_reply(user_text: str, chat_key: str) -> str:
    hist = await memory.get_history(chat_key)
    profile = await memory.get_profile(chat_key)

    lines = []
    if profile:
        lines.append(f"[Память о пользователе: {profile[:500]}]")
    for role, text in hist[-10:]:
        who = "Пользователь" if role == "user" else "Shyni"
        lines.append(f"{who}: {text[:300]}")
    lines.append(f"Пользователь: {user_text[:1000]}\nShyni:")
    prompt = "\n".join(lines)

    client = get_client()
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            log(f"Gemma {config.GEMMA_MODEL} запрос, попытка {attempt}/{MAX_ATTEMPTS}...")
            t0 = time.time()
            # Как рекомендует Google: Chat.send_message вместо Models.generate_content.
            # Чат одноразовый на запрос - история у нас своя в sqlite, сюда уходит готовый промпт.
            chat = await asyncio.to_thread(
                client.chats.create, *(),
                **dict(model=config.GEMMA_MODEL, config=_make_config()),
            )
            resp = await asyncio.to_thread(chat.send_message, prompt)
            dt = time.time() - t0
            text = (getattr(resp, "text", None) or "").strip()
            log(f"ответ за {dt:.1f}с, длина {len(text)}: {text[:120]!r}")
            if text:
                if len(text) > 400:
                    text = text[:397] + "..."
                return text
            last_err = "пустой text в ответе"
            log(f"попытка {attempt}: {last_err}"[:300])
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            log(f"попытка {attempt} ОШИБКА: {last_err}"[:300])
        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(min(2 * attempt, 8))
    log(f"все попытки упали, отдаю fallback (last={last_err})"[:200])
    return random.choice(FALLBACKS)
