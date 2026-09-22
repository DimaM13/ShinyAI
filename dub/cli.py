"""Даббинг видео поверх текущего стека Shyni. Ничего нового не качает:
- faster-whisper (уже в .venv) - транскрибация с таймингами сегментов
- Gemma 26b-a4b (тот же ключ) - перевод
- Qwen3-TTS Base (уже в кэше) - синтез клоном
- ffmpeg - склейка

Режимы голоса:
  --voice orig        клон голоса из самого видео (x-vector, транскрипт не нужен)
  --voice <имя>       любой голос из base_voices (shyni, kira, timur...)

Тайминг: каждый сегмент стартует в свое время оригинала. Если синтез длиннее -
ускоряем atempo (до 2x), если короче - добиваем тишиной. Оригинал можно
подмешать тихо фоном через --bg 0.15 (0 = полная замена).

Запуск из папки Shyni локальным venv:
  .\\.venv\\Scripts\\python.exe dub\\cli.py input.mp4 --dst en --voice orig
  .\\.venv\\Scripts\\python.exe dub\\cli.py input.mp4 --dst ru --voice kira --out out.mp4
"""
import argparse
import faulthandler
import os
import subprocess
import sys
import tempfile

faulthandler.enable()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SR = 24000


def slog(msg: str):
    # в путях бывают эмодзи - консоль cp1251 их не тянет
    print(str(msg).encode("cp1251", "backslashreplace").decode("cp1251"), flush=True)


def run(cmd):
    try:
        # encoding utf-8 + replace: вывод ffmpeg может содержать эмодзи из имен файлов,
        # штатная cp1251 на них падает с UnicodeDecodeError в потоке чтения
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg fail [{e.returncode}]: {(e.stderr or '')[-500:]}")


def extract_audio(video: str, out_wav: str):
    run(["ffmpeg", "-y", "-i", video, "-ar", str(SR), "-ac", "1", out_wav])


def transcribe(wav: str, src: str):
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(wav, language=None if src == "auto" else src, vad_filter=True)
    out = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments if s.text.strip()]
    print(f"[dub] сегментов речи: {len(out)}")
    return out


def translate_batch(texts, src: str, dst: str, budgets=None, tries: int = 8):
    from google import genai
    from google.genai import types
    import config
    import time
    client = genai.Client(api_key=config.GOOGLE_API_KEY)
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    limits = ""
    if budgets:
        limits = ("\nHard length limits (MAX characters per line, cut adjectives/filler but keep meaning): "
                  + ", ".join(f"{i + 1}:{b}" for i, b in enumerate(budgets)) + "\n")
        prompt = (
            f"Translate from {src} to {dst}. Each line MUST fit its character limit - "
            f"this is voiceover timing, shorter is fine, longer is broken. "
            f"No explanations. Return ONLY the numbered lines in the same format 'N. text'.\n"
            f"{limits}{numbered}"
        )
    else:
        prompt = (
            f"Translate from {src} to {dst}. Keep each line short, similar length to source, "
            f"no explanations. Return ONLY the numbered lines in the same format 'N. text'.\n{numbered}"
        )
    last = None
    for attempt in range(1, tries + 1):
        try:
            resp = client.models.generate_content(
                model=config.GEMMA_MODEL,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=2000,
                    thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
                contents=prompt,
            )
            break
        except Exception as e:  # 503/500 при перегрузе - ждем и долбим дальше
            last = e
            time.sleep(min(3 * attempt, 20))
    else:
        raise last
    lines = (resp.text or "").strip().split("\n")
    out = []
    for i in range(len(texts)):
        if i < len(lines) and lines[i].lstrip()[: len(str(i + 1)) + 1].rstrip(". ") == str(i + 1):
            out.append(lines[i].split(".", 1)[1].strip() if "." in lines[i] else lines[i].strip())
        else:
            out.append(lines[i].strip() if i < len(lines) else texts[i])
    return out


CPS = 14  # символов/сек русского синтеза - из него бюджет строки
MAX_TEMPO = 1.4  # выше не ускоряем чтобы не было бурундука, остаток режем
RESYNTH_RATIO = 1.6  # вылез сильнее - просим короче и перегенерим (флаг --resynth)


def slot_of(segments, i: int) -> float:
    end = segments[i + 1]["start"] if i + 1 < len(segments) else segments[i]["end"]
    return max(0.5, end - segments[i]["start"])


def translate_all(segments, src: str, dst: str, log=print):
    res = []
    for i in range(0, len(segments), 8):
        chunk = segments[i:i + 8]
        budgets = [int(slot_of(segments, j) * CPS) for j in range(i, i + len(chunk))]
        log(f"[dub] перевод {i + 1}-{i + len(chunk)}/{len(segments)}...")
        res.extend(translate_batch([s["text"] for s in chunk], src, dst, budgets=budgets))
    return res


def shorten_text(text: str, budget: int, dst: str) -> str:
    """Одна попытка ужаться: просим Gemma короче под бюджет символов."""
    from google import genai
    from google.genai import types
    import config
    import time
    client = genai.Client(api_key=config.GOOGLE_API_KEY)
    last = text
    for attempt in range(1, 4):
        try:
            resp = client.models.generate_content(
                model=config.GEMMA_MODEL,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=300,
                    thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
                contents=(f"Shorten this {dst} voiceover line to at most {budget} characters, "
                          f"keep the core meaning. Output ONLY the shortened line, nothing else.\n{last}"),
            )
            cand = (resp.text or "").strip()
            if cand:
                return cand
        except Exception:
            time.sleep(min(3 * attempt, 10))
    return last


def fit_filter(tts_dur: float, seg_dur: float) -> tuple:
    """Подгонка чанка строго под слот. Возвращает (фильтр, пожат_ли).
    Ускорение capped MAX_TEMPO чтобы не было бурундука, остаток режем."""
    if tts_dur > seg_dur * 1.05:
        ratio = min(tts_dur / seg_dur, MAX_TEMPO)
        squeezed = tts_dur / seg_dur > MAX_TEMPO
        return f"atempo={ratio:.3f},atrim=0:{seg_dur:.3f},asetpts=PTS-STARTPTS", squeezed
    if tts_dur < seg_dur * 0.9:
        return f"apad=whole_dur={seg_dur:.3f},asetpts=PTS-STARTPTS", False
    return "anull,asetpts=PTS-STARTPTS", False


def build_dub_track(chunks, total_dur: float, out_wav: str, bg_wav=None, bg_vol: float = 0.0, log=print):
    """chunks: [(wav_path, start_sec)]. Каждый стартует в свое время."""
    import soundfile as sf
    inputs, filters, mix = [], [], []
    squeezed_n = 0
    for i, (path, start) in enumerate(chunks):
        inputs += ["-i", path]
        info = sf.info(path)
        seg_end = chunks[i + 1][1] if i + 1 < len(chunks) else total_dur
        seg_dur = max(0.3, seg_end - start)
        dur = info.frames / info.samplerate
        filt, squeezed = fit_filter(dur, seg_dur)
        if squeezed:
            squeezed_n += 1
            log(f"[dub] кусок {i + 1}: перевод длиннее слота, ускорен {MAX_TEMPO}x + резан")
        filters.append(f"[{i}:a]{filt},adelay={int(start * 1000)}|{int(start * 1000)}[a{i}]")
        mix.append(f"[a{i}]")
    if squeezed_n:
        log(f"[dub] пожато кусков: {squeezed_n}/{len(chunks)}")
    n = len(chunks)
    if bg_wav and bg_vol > 0:
        inputs += ["-i", bg_wav]
        filters.append(f"[{n}:a]volume={bg_vol}[bg]")
        mix.append("[bg]")
        n += 1
    filters.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=longest[out]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters),
         "-map", "[out]", "-t", f"{total_dur:.3f}", "-ar", str(SR), "-ac", "1", out_wav])


def mux(video: str, dub_wav: str, out_mp4: str):
    run(["ffmpeg", "-y", "-i", video, "-i", dub_wav,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
         "-shortest", out_mp4])


def run_job(job: dict, log=print):
    """Весь пайплайн одним вызовом. job: input/dst/src/voice/out/bg/lang.
    Возвращает путь к готовому видео."""
    import config
    import settings
    import tts_voice

    out_mp4 = job.get("out") or os.path.splitext(job["input"])[0] + "_dubbed.mp4"
    dst, src = job.get("dst", "en"), job.get("src", "auto")
    synth_lang = {"en": "English", "ru": "Russian"}.get((job.get("lang") or dst).lower(), dst)
    work = tempfile.mkdtemp(prefix="shyni_dub_")
    orig_wav = os.path.join(work, "orig.wav")

    log("[dub] 1/5 вытаскиваю аудио...")
    extract_audio(job["input"], orig_wav)
    import soundfile as sf
    total_dur = sf.info(orig_wav).frames / SR

    log("[dub] 2/5 транскрибация...")
    segments = transcribe(orig_wav, src)
    if not segments:
        log("[dub] речи не найдено, нечего дублировать")
        return None

    log("[dub] 3/5 перевод...")
    translated = translate_all(segments, src, dst, log=log)

    log("[dub] 4/5 синтез...")
    model = tts_voice.get_model()
    voice = job.get("voice", "orig")
    if voice == "orig":
        # эталон - первые ~20 сек речи, x-vector (транскрипт не нужен)
        ref_end = min(20.0, segments[min(2, len(segments) - 1)]["end"])
        ref_wav = os.path.join(work, "ref.wav")
        run(["ffmpeg", "-y", "-i", orig_wav, "-ss", "0", "-t", str(ref_end), ref_wav])
        prompt = model.create_voice_clone_prompt(ref_audio=ref_wav, x_vector_only_mode=True)
        gen = lambda t: model.generate_voice_clone(
            text=tts_voice.clean_for_tts(t), language=synth_lang, voice_clone_prompt=prompt)
    else:
        if settings.get_base_voice_row(voice) is None:
            log(f"[dub] нет такого голоса: {voice}")
            return None
        prompt = tts_voice.get_clone_prompt(voice)
        gen = lambda t: model.generate_voice_clone(
            text=tts_voice.clean_for_tts(t), language=synth_lang, voice_clone_prompt=prompt)

    chunks = []
    resynth = bool(job.get("resynth", False))
    for i, (seg, text) in enumerate(zip(segments, translated)):
        slot = slot_of(segments, i)
        wavs, sr = gen(text)
        dur = len(wavs[0]) / sr
        if resynth and dur > slot * RESYNTH_RATIO:
            budget = int(slot * CPS)
            log(f"[dub] кусок {i + 1}: вылез ({dur:.1f}с в слот {slot:.1f}с), прошу короче...")
            text2 = shorten_text(text, budget, dst)
            wavs, sr = gen(text2)
            log(f"[dub] кусок {i + 1}: перегенерил ({len(wavs[0]) / sr:.1f}с)")
        path = os.path.join(work, f"ch{i:03d}.wav")
        sf.write(path, wavs[0], sr)
        chunks.append((path, seg["start"]))
        log(f"[dub] синтез {i + 1}/{len(segments)}")

    log("[dub] 5/5 укладка по времени и склейка...")
    dub_wav = os.path.join(work, "dub.wav")
    bg = float(job.get("bg", 0.0))
    build_dub_track(chunks, total_dur, dub_wav,
                    bg_wav=orig_wav if bg > 0 else None, bg_vol=bg, log=log)
    mux(job["input"], dub_wav, out_mp4)
    log(f"[dub] ГОТОВО: {out_mp4}")
    return out_mp4


def main():
    ap = argparse.ArgumentParser(description="Shyni dub: перевод видео с даббингом")
    ap.add_argument("input", help="входное видео")
    ap.add_argument("--dst", default="en", help="язык перевода (en/ru/...)")
    ap.add_argument("--src", default="auto", help="язык оригинала (auto/ru/en/...)")
    ap.add_argument("--voice", default="orig", help="orig или имя голоса из base_voices")
    ap.add_argument("--out", default=None, help="выходное видео (по умолч. input_dubbed.mp4)")
    ap.add_argument("--bg", type=float, default=0.0, help="громкость оригинала фоном 0-1")
    ap.add_argument("--lang", default=None, help="язык синтеза (по умолч. = dst)")
    ap.add_argument("--resynth", action="store_true",
                    help="вылезшие куски (>1.6x слота) сократить через Gemma и перегенерить")
    args = ap.parse_args()
    run_job(vars(args), log=lambda m: slog(m))


if __name__ == "__main__":
    main()
