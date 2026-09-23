# 💬 Shyni — голосовая аниме-вайфу в Telegram

Shyni живёт в Telegram, общается **только голосовыми**: ей пишут текстом, она отвечает войсом. Работает в личке и в группах, помнит собеседников.

## 🧠 Как устроено

```
текст юзера → Gemma (характер + память) → Qwen3-TTS (клон голоса) → voice.ogg
```

| Компонент | Что | Зачем |
|---|---|---|
| Мозг | `gemma-4-26b-a4b-it` через Google AI Studio | Быстрый MoE: ответ ~3 сек вместо 30-50 у dense 31B |
| Голос | `Qwen3-TTS-12Hz-1.7B-Base` ([стриминг-форк](https://github.com/dffdeeq/Qwen3-TTS-streaming)) | Клон голоса по эталону, ~4 сек на фразу |
| Память | SQLite (`shyni.db`) | ЛС — память на юзера, группа — на пару чат+юзер, последние 10-20 реплик |
| Бот | `aiogram 3` | В группе отвечает только на реплай/упоминание |

Голос по умолчанию — `shyni` (русская девочка-эталон в `voices/`). Другие голоса добавляются файлами (аудио + дословный транскрипт) и выбираются в `/settings` (только владелец).

## 🖥 Требования

- Windows + Python 3.12 + **NVIDIA GPU 8GB+** (проверено на RTX 3050)
- Без GPU TTS считает 30+ сек на фразу — для болталки мертво
- Бот и остальные проекты (даббер, каверы) делят одну видюху — одновременно не живут, останавливай бота перед ними

## 🚀 Установка

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130
.\.venv\Scripts\python -m pip install -U "triton-windows<3.7"
git clone https://github.com/dffdeeq/Qwen3-TTS-streaming.git
.\.venv\Scripts\python -m pip install -e ./Qwen3-TTS-streaming --no-deps
.\.venv\Scripts\python -m pip install -r requirements.txt
# + ffmpeg и sox в PATH (winget: ffmpeg, ChrisBagwell.SoX)
copy .env.example .env   # и вставь свои ключи
.\.venv\Scripts\python -m pip install transformers==4.57.3  # версия важна, иначе форк крашится
.\.venv\Scripts\python bot.py
```

Первый старт греется 1-4 мин (загрузка весов + компиляция inductor, кэш потом сохраняется). Дальше ответы ~3 сек мозг + ~4 сек голос.

## 🔑 Ключи

- Токен — [@BotFather](https://t.me/BotFather). **Никогда не пости токен в чаты** — любой увидевший получает управление ботом. Если засветил — `/revoke` и новый.
- `GOOGLE_API_KEY` — Google AI Studio.
- В группе отключи privacy (`/setprivacy` → Disable), иначе бот не увидит упоминания. Либо хватит реплаев — они работают и так.

## ⚙ Настройки (`/settings`, только владелец)

- Выбор голоса клона из добавленных
- Характер правится в `config.py` → `SHYNI_SYSTEM`
- Параметры Gemma (`temperature`, лимиты) — `brain.py`

## 📌 Из опыта

- `flash_attn` wheel из доки форка собран под torch 2.10 и не грузится на новых версиях — едем на `sdpa`, потеря небольшая
- `transformers` строго `==4.57.3`, иначе `check_model_inputs()` крашит импорт
- Thinking-моделям Gemma нужен `thinking_level="MINIMAL"` + запас `max_output_tokens`, иначе 40 сек думания и пустой ответ
- TTS читает `*ремарки*` и `дефисы-в-словах` буквально — чистка в `tts_voice.clean_for_tts`, а цифры/версии Gemma пишет словами (иначе "4.7" коверкается)
