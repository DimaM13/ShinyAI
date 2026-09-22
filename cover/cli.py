"""Кавер/даббинг через RVC: видео -> demucs(голос отдельно) -> RVC -> музыка назад -> mux.

Музыка полностью вырезается ДО RVC (чтобы модель ее не захватила),
после озвучки фоновая музыка подмешивается обратно.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SR_OUT = 40000


def run(cmd):
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg fail [{e.returncode}]: {(e.stderr or '')[-500:]}")


def separate(vocals_wav_44k: str, work: str):
    """demucs -> (vocals_44k, music_44k)."""
    out_dir = os.path.join(work, "demucs_out")
    cmd = [sys.executable, "-m", "demucs", "--two-stems", "vocals", "-o", out_dir, vocals_wav_44k]
    try:
        subprocess.run(cmd + ["-d", "cuda"], check=True, capture_output=True)
    except Exception:
        subprocess.run(cmd + ["-d", "cpu"], check=True, capture_output=True)
    voc = mus = None
    for root, _, files in os.walk(out_dir):
        if "vocals.wav" in files:
            voc = os.path.join(root, "vocals.wav")
        if "no_vocals.wav" in files:
            mus = os.path.join(root, "no_vocals.wav")
    if not voc or not mus:
        raise RuntimeError("demucs не отдал дорожки")
    return voc, mus


def run_job(job: dict, log=print):
    """job: input/voice/transpose/index_rate/rms_mix/protect/music(bool)/music_vol/out.
    Возвращает путь к готовому видео."""
    import numpy as np
    import soundfile as sf
    import librosa
    from cover._rvc import rvc
    from cover import voices, pitch

    vinfo = voices.load().get(job["voice"])
    if not vinfo:
        log(f"[cover] нет такого голоса: {job['voice']}")
        return None

    work = tempfile.mkdtemp(prefix="shyni_cover_")
    in44 = os.path.join(work, "in44.wav")
    log("[cover] 1/5 аудио из видео...")
    run(["ffmpeg", "-y", "-i", job["input"], "-ar", "44100", "-ac", "2", in44])
    total_dur = sf.info(in44).frames / 44100

    log("[cover] 2/5 вырезаю музыку (demucs, чтобы RVC ее не захватил)...")
    voc44, mus44 = separate(in44, work)

    log("[cover] 3/5 анализ голоса + параметры...")
    v16, _ = librosa.load(voc44, sr=16000, mono=True)
    stats = pitch.source_stats(v16.astype("float32"))
    transpose = job.get("transpose")
    if transpose is None:
        transpose = pitch.suggest_transpose(stats["median"], vinfo["type"])
        log(f"[cover] автотон: F0 {stats['median']:.0f} -> {transpose:+d} полутонов ({vinfo['type']})")
    params = job.get("params") or pitch.gemma_params(
        f"{'песня' if stats['voiced'] > 0.5 else 'речь'}, {total_dur:.0f} сек",
        job["voice"], vinfo["type"], stats["median"], transpose)
    log(f"[cover] Gemma: index={params['index_rate']} rms={params['rms_mix_rate']} protect={params['protect']}")

    log("[cover] 4/5 RVC-конвертация...")
    pack = rvc.load(vinfo["pth"], vinfo.get("index"))
    out, sr = rvc.convert(pack, v16.astype("float32"), transpose=transpose,
                          index_rate=params["index_rate"],
                          rms_mix_rate=params["rms_mix_rate"], protect=params["protect"])
    conv_wav = os.path.join(work, "conv.wav")
    sf.write(conv_wav, out, sr)

    log("[cover] 5/5 музыка назад + склейка...")
    mux_in = ["-i", conv_wav]
    filt = "[0:a]aresample=44100,aformat=channel_layouts=stereo[voice]"
    if job.get("music", True):
        mux_in += ["-i", mus44]
        vol = float(job.get("music_vol", 1.0))
        filt += f";[1:a]aresample=44100,aformat=channel_layouts=stereo,volume={vol}[bg];[voice][bg]amix=inputs=2:normalize=0[aout]"
    else:
        filt += ";[voice]acopy[aout]"
    out_mp4 = job.get("out") or os.path.splitext(job["input"])[0] + "_cover.mp4"
    run(["ffmpeg", "-y", "-i", job["input"], *mux_in, "-filter_complex", filt,
         "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac",
         "-shortest", out_mp4])
    log(f"[cover] ГОТОВО: {out_mp4}")
    return out_mp4


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Shyni cover: RVC-даббинг видео")
    ap.add_argument("input")
    ap.add_argument("--voice", required=True)
    ap.add_argument("--transpose", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--music-vol", type=float, default=1.0)
    args = ap.parse_args()
    run_job({"input": args.input, "voice": args.voice, "transpose": args.transpose,
             "out": args.out, "music": not args.no_music, "music_vol": args.music_vol},
            log=lambda m: print(str(m).encode("cp1251", "backslashreplace").decode("cp1251"), flush=True))


if __name__ == "__main__":
    main()
