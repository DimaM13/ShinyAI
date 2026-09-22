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
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SR = 24000


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def extract_audio(video: str, out_wav: str):
    run(["ffmpeg", "-y", "-i", video, "-ar", str(SR), "-ac", "1", out_wav])


def transcribe(wav: str, src: str):
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(wav, language=None if src == "auto" else src, vad_filter=True)
    out = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments if s.text.strip()]
    print(f"[dub] сегментов речи: {len(out)}")
    return out


def translate_batch(texts, src: str, dst: str):
    from google import genai
    from google.genai import types
    import config
    client = genai.Client(api_key=config.GOOGLE_API_KEY)
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    prompt = (
        f"Translate from {src} to {dst}. Keep each line short, similar length to source, "
        f"no explanations. Return ONLY the numbered lines in the same format 'N. text'.\n{numbered}"
    )
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
    lines = (resp.text or "").strip().split("\n")
    out = []
    for i in range(len(texts)):
        if i < len(lines) and lines[i].lstrip()[: len(str(i + 1)) + 1].rstrip(". ") == str(i + 1):
            out.append(lines[i].split(".", 1)[1].strip() if "." in lines[i] else lines[i].strip())
        else:
            out.append(lines[i].strip() if i < len(lines) else texts[i])
    return out


def translate_all(segments, src: str, dst: str):
    res = []
    for i in range(0, len(segments), 8):
        chunk = segments[i:i + 8]
        print(f"[dub] перевод {i + 1}-{i + len(chunk)}/{len(segments)}...")
        res.extend(translate_batch([s["text"] for s in chunk], src, dst))
    return res


def atempo_chain(ratio: float) -> str:
    """atempo держит 0.5-2.0 за раз, цепочкой покрываем шире."""
    parts = []
    r = max(0.5, min(2.0, ratio))
    while r > 2.0:
        parts.append("atempo=2.0")
        r /= 2.0
    parts.append(f"atempo={r:.3f}")
    return ",".join(parts)


def fit_filter(tts_dur: float, seg_dur: float) -> str:
    """Фильтр подгонки чанка под длительность сегмента."""
    if tts_dur > seg_dur * 1.05:
        return atempo_chain(tts_dur / seg_dur)
    if tts_dur < seg_dur * 0.9:
        return f"apad=whole_dur={seg_dur:.3f}"
    return "anull"


def build_dub_track(chunks, total_dur: float, out_wav: str, bg_wav=None, bg_vol: float = 0.0):
    """chunks: [(wav_path, start_sec)]. Каждый стартует в свое время."""
    import soundfile as sf
    inputs, filters, mix = [], [], []
    for i, (path, start) in enumerate(chunks):
        inputs += ["-i", path]
        info = sf.info(path)
        seg_end = chunks[i + 1][1] if i + 1 < len(chunks) else total_dur
        seg_dur = max(0.3, seg_end - start)
        dur = info.frames / info.samplerate
        filters.append(f"[{i}:a]{fit_filter(dur, seg_dur)},adelay={int(start * 1000)}|{int(start * 1000)}[a{i}]")
        mix.append(f"[a{i}]")
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


def main():
    ap = argparse.ArgumentParser(description="Shyni dub: перевод видео с даббингом")
    ap.add_argument("input", help="входное видео")
    ap.add_argument("--dst", default="en", help="язык перевода (en/ru/...)")
    ap.add_argument("--src", default="auto", help="язык оригинала (auto/ru/en/...)")
    ap.add_argument("--voice", default="orig", help="orig или имя голоса из base_voices")
    ap.add_argument("--out", default=None, help="выходное видео (по умолч. input_dubbed.mp4)")
    ap.add_argument("--bg", type=float, default=0.0, help="громкость оригинала фоном 0-1")
    ap.add_argument("--lang", default=None, help="язык синтеза (по умолч. = dst)")
    args = ap.parse_args()

    import config
    import settings
    import tts_voice

    out_mp4 = args.out or os.path.splitext(args.input)[0] + "_dubbed.mp4"
    synth_lang = {"en": "English", "ru": "Russian"}.get((args.lang or args.dst).lower(), args.dst)
    work = tempfile.mkdtemp(prefix="shyni_dub_")
    orig_wav = os.path.join(work, "orig.wav")

    print("[dub] 1/5 вытаскиваю аудио...")
    extract_audio(args.input, orig_wav)
    import soundfile as sf
    total_dur = sf.info(orig_wav).frames / SR

    print("[dub] 2/5 транскрибация...")
    segments = transcribe(orig_wav, args.src)
    if not segments:
        print("[dub] речи не найдено, нечего дублировать")
        return

    print("[dub] 3/5 перевод...")
    translated = translate_all(segments, args.src, args.dst)

    print("[dub] 4/5 синтез...")
    model = tts_voice.get_model()
    if args.voice == "orig":
        # эталон - первые ~20 сек речи, x-vector (транскрипт не нужен)
        ref_end = min(20.0, segments[min(2, len(segments) - 1)]["end"])
        ref_wav = os.path.join(work, "ref.wav")
        run(["ffmpeg", "-y", "-i", orig_wav, "-ss", "0", "-t", str(ref_end), ref_wav])
        prompt = model.create_voice_clone_prompt(ref_audio=ref_wav, x_vector_only_mode=True)
        gen = lambda t: model.generate_voice_clone(
            text=tts_voice.clean_for_tts(t), language=synth_lang, voice_clone_prompt=prompt)
    else:
        if settings.get_base_voice_row(args.voice) is None:
            print(f"[dub] нет такого голоса: {args.voice}")
            return
        prompt = tts_voice.get_clone_prompt(args.voice)
        gen = lambda t: model.generate_voice_clone(
            text=tts_voice.clean_for_tts(t), language=synth_lang, voice_clone_prompt=prompt)

    chunks = []
    for i, (seg, text) in enumerate(zip(segments, translated)):
        wavs, sr = gen(text)
        path = os.path.join(work, f"ch{i:03d}.wav")
        sf.write(path, wavs[0], sr)
        chunks.append((path, seg["start"]))
        print(f"[dub] синтез {i + 1}/{len(segments)}")

    print("[dub] 5/5 укладка по времени и склейка...")
    dub_wav = os.path.join(work, "dub.wav")
    build_dub_track(chunks, total_dur, dub_wav,
                    bg_wav=orig_wav if args.bg > 0 else None, bg_vol=args.bg)
    mux(args.input, dub_wav, out_mp4)
    print(f"[dub] ГОТОВО: {out_mp4}")


if __name__ == "__main__":
    main()
