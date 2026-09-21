import os
# Глушим спам torch._dynamo/_inductor ДО импорта torch
os.environ.setdefault("TORCHDYNAMO_VERBOSE", "0")
os.environ.setdefault("TORCH_LOGS", "-all")
os.environ.setdefault("TORCHDYNAMO_REPRO_LEVEL", "0")
import warnings
warnings.filterwarnings("ignore")
import logging
for _n in ("torch._dynamo", "torch._inductor", "torch._functorch"):
    logging.getLogger(_n).setLevel(logging.ERROR)

import torch
import numpy as np
import soundfile as sf
import subprocess
import tempfile
import os as _os
import time
import config

torch.set_float32_matmul_precision("high")
try:
    import torch._dynamo
    torch._dynamo.config.suppress_errors = True
    torch._dynamo.config.verbose = False
    try:
        from torch._logging import set_logs
        set_logs(dynamo=logging.ERROR, inductor=logging.ERROR, aot=logging.ERROR)
    except Exception:
        pass
except Exception:
    pass

_model = None
_clone_prompt = None

def get_model():
    global _model
    if _model is None:
        from qwen_tts import Qwen3TTSModel
        try:
            _model = Qwen3TTSModel.from_pretrained(
                config.QWEN_MODEL_ID,  # Qwen/Qwen3-TTS-12Hz-1.7B-Base
                device_map="cuda:0",
                dtype=torch.bfloat16,
                attn_implementation="flash_attention_2",
            )
        except Exception:
            # без flash_attn на Windows падаем на sdpa, медленнее но работает
            _model = Qwen3TTSModel.from_pretrained(
                config.QWEN_MODEL_ID,
                device_map="cuda:0",
                dtype=torch.bfloat16,
                attn_implementation="sdpa",
            )
        # Оптимизации из dffdeeq форка. На Windows+3050 triton/inductor часто падает -
        # тогда едем на eager без компиляции, медленнее но стабильно.
        # use_compile=False сразу: без triton compile все равно падает в fallback,
        # только спамит в консоль. Быстрого пути без flash-attn+triton нет.
        try:
            _model.enable_streaming_optimizations(
                decode_window_frames=80,
                use_compile=False,
                use_cuda_graphs=False,
                compile_mode="reduce-overhead",
                use_fast_codebook=True,
                compile_codebook_predictor=False,
                compile_talker=False,
            )
            print("[tts] eager mode (без torch.compile, тихо и стабильно)")
        except Exception as e2:
            print(f"[tts] optimizations skipped: {e2}")
    return _model

import re

# Ремарки вида *хихикает*, [смеется], (пауза), эмодзи - TTS читает их вслух как текст.
# Режем перед синтезом. История в brain.py хранит оригинал, сюда приходит уже чистка.
_RE_STAR = re.compile(r"\*[^*]+\*")
_RE_SQUARE = re.compile(r"\[[^\]]+\]")
_RE_PAREN = re.compile(r"\([^)]+\)")
_RE_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]"
)
_RE_WS = re.compile(r"\s+")

def clean_for_tts(text: str) -> str:
    t = _RE_STAR.sub(" ", text)
    t = _RE_SQUARE.sub(" ", t)
    # скобки режем только короткие ремарки, длинные оставляем (там может быть смысл)
    t = _RE_PAREN.sub(lambda m: " " if len(m.group(0)) < 40 else m.group(0), t)
    t = _RE_EMOJI.sub("", t)
    t = t.replace("*", "").replace("#", "")
    t = _RE_WS.sub(" ", t).strip(" ,.-")
    return t or "Хихи... повтори еще раз!"

def get_clone_prompt():
    global _clone_prompt
    if _clone_prompt is None:
        m = get_model()
        _clone_prompt = m.create_voice_clone_prompt(
            ref_audio=config.REF_AUDIO,  # voices/shyni_ref.wav - русская девочка
            ref_text=config.REF_TEXT,
        )
    return _clone_prompt

def speak_to_ogg(text: str, out_ogg: str):
    """Текст -> чистка ремарок -> wav 24kHz через dffdeeq клон -> ogg opus для ТГ voice."""
    clean = clean_for_tts(text)
    if clean != text:
        print(f"[tts] чистка: {text[:80]!r} -> {clean[:80]!r}")
    m = get_model()
    prompt = get_clone_prompt()
    wavs, sr = m.generate_voice_clone(
        text=clean,
        language=config.TTS_LANG,
        voice_clone_prompt=prompt,
    )
    audio = wavs[0]

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp_wav = tf.name
    try:
        sf.write(tmp_wav, audio, sr)
        # ffmpeg обязателен, качаем с ffmpeg.org, кладем в PATH
        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_wav, "-c:a", "libopus", "-b:a", "64k", out_ogg],
            check=True, capture_output=True,
        )
    finally:
        if _os.path.exists(tmp_wav):
            _os.remove(tmp_wav)
    return out_ogg
