"""Разовый импорт голосов из NastyaAi: транскрипция эталонов + копия аудио + регистрация в БД."""
import os
import shutil
import subprocess
import sys

SRC = r"C:\Users\dimam\OneDrive\Документы\NastyaAi 4.0 with local F5 tts universal\VOICES"
DST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")

FILES = [
    "alina.wav", "female_sample.wav", "girllittle.wav", "igor.wav",
    "kaluvan.wav", "Kira.wav", "kuriamamirai.wav", "progmata.wav",
    "Timur.wav", "tonistark.mp3", "yurii.wav",
]

os.makedirs(DST, exist_ok=True)

from faster_whisper import WhisperModel
print("грузю whisper small (cpu)...", flush=True)
model = WhisperModel("small", device="cpu", compute_type="int8")

import settings
settings.init_settings()

for f in FILES:
    name = os.path.splitext(f)[0].lower()
    src = os.path.join(SRC, f)
    # mp3 -> wav чтобы Qwen точно прочитал
    if f.endswith(".mp3"):
        dst = os.path.join(DST, name + ".wav")
        if not os.path.exists(dst):
            subprocess.run(["ffmpeg", "-y", "-i", src, "-ar", "24000", "-ac", "1", dst],
                           check=True, capture_output=True)
    else:
        dst = os.path.join(DST, f)
        if not os.path.exists(dst):
            shutil.copy(src, dst)
    print(f"[{name}] транскрибирую {f}...", flush=True)
    segments, info = model.transcribe(dst, language="ru")
    text = " ".join(s.text.strip() for s in segments).strip()
    print(f"[{name}] lang={info.language} -> {text[:100]!r}", flush=True)
    rel = os.path.join("voices", os.path.basename(dst))
    settings.add_base_voice(name, rel, text)

print("ГОТОВО:", [r[0] for r in settings.list_base_voices()], flush=True)
