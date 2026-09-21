import asyncio
import random
import time
from google import genai
from google.genai import types
import config
import memory

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

FALLBACKS = [
    "Хихи... сервак Гугла чихнул, повтори еще разок!",
    "Ой, мои мозги подвисли... скажи еще раз, пожалуйста!",
    "Бака, нейронка моя глюканула! Повтори, а?",
]

async def shyni_reply(user_text: str, chat_key: str) -> str:
    hist = await memory.get_history(chat_key)
    profile = await memory.get_profile(chat_key)

    contents = []
    if profile:
        contents.append(f"[Память о пользователе: {profile}]")
    for role, text in hist[-10:]:
        who = "Пользователь" if role == "user" else "Shyni"
        contents.append(f"{who}: {text}")
    contents.append(f"Пользователь: {user_text}\nShyni:")

    client = get_client()
    last_err = None
    for attempt in (1, 2, 3):
        try:
            log(f"Gemma {config.GEMMA_MODEL} запрос, попытка {attempt}...")
            t0 = time.time()
            resp = await asyncio.to_thread(
                client.models.generate_content,
                *(),
                **dict(
                    model=config.GEMMA_MODEL,  # gemma-4-31b-it
                    config=types.GenerateContentConfig(
                        system_instruction=config.SHYNI_SYSTEM,
                        temperature=0.9,
                        max_output_tokens=500,
                        # Без этого модель 40с "думает" и ответ не влезает в лимит -> пустой text
                        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
                    ),
                    contents="\n".join(contents),
                ),
            )
            dt = time.time() - t0
            text = (getattr(resp, "text", None) or "").strip()
            log(f"ответ за {dt:.1f}с, длина {len(text)}: {text[:120]!r}")
            if text:
                if len(text) > 400:
                    text = text[:397] + "..."
                return text
            last_err = "пустой text в ответе"
            log(f"попытка {attempt}: {last_err}, candidates={getattr(resp, 'candidates', None)!r}"[:300])
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            log(f"попытка {attempt} ОШИБКА: {last_err}"[:300])
            if attempt < 3:
                await asyncio.sleep(2 * attempt)
    log(f"все попытки упали, отдаю fallback (last={last_err})"[:200])
    return random.choice(FALLBACKS)
