"""Загрузка RVC-модели + конвертация файла целиком (с нарезкой длинного по тишине)."""
import os
import numpy as np
import torch
import faiss
import librosa

from .rvclib.models import SynthesizerTrnMs768NSFsid, SynthesizerTrnMs768NSFsid_nono
from . import pipe

_cache = {}


def load(model_path: str, index_path: str | None = None, device: str = "cuda:0", is_half: bool = True):
    key = (model_path, device, is_half)
    if key in _cache:
        return _cache[key]
    cpt = torch.load(model_path, map_location="cpu")
    cfg = list(cpt["config"])
    cfg[-3] = cpt["weight"]["emb_g.weight"].shape[0]
    if_f0 = cpt.get("f0", 1)
    cls = SynthesizerTrnMs768NSFsid if if_f0 == 1 else SynthesizerTrnMs768NSFsid_nono
    net_g = cls(*cfg, is_half=is_half)
    try:
        del net_g.enc_q
    except Exception:
        pass
    net_g.load_state_dict(cpt["weight"], strict=False)
    net_g.eval().to(device)
    net_g = net_g.half() if is_half else net_g.float()
    tgt_sr = cfg[-1]
    index, index_vecs = None, None
    if index_path and os.path.exists(index_path):
        index = faiss.read_index(index_path)
        index_vecs = index.reconstruct_n(0, index.ntotal)
    pack = {"net": net_g, "tgt_sr": tgt_sr, "index": index,
            "index_vecs": index_vecs, "if_f0": if_f0, "device": device, "is_half": is_half}
    _cache[key] = pack
    n = sum(p.numel() for p in net_g.parameters()) / 1e6
    print(f"[rvc] модель {os.path.basename(model_path)}: {n:.1f}M params, sr={tgt_sr}, f0={if_f0}")
    return pack


def split_silence(audio_16k: np.ndarray, max_len_s: float = 60.0):
    """Режем длинное на куски по тишине чтобы не лопнуть VRAM."""
    max_n = int(max_len_s * 16000)
    if len(audio_16k) <= max_n:
        return [(0, len(audio_16k))]
    intervals = librosa.effects.split(audio_16k, top_db=35)
    cuts, start = [0], 0
    for s, e in intervals:
        if e - start >= max_n:
            cuts.append(s)
            start = s
    cuts.append(len(audio_16k))
    return list(zip(cuts[:-1], cuts[1:]))


def convert(pack, audio_16k: np.ndarray, transpose: int = 0, index_rate: float = 0.75,
            rms_mix_rate: float = 1.0, protect: float = 0.33) -> tuple[np.ndarray, int]:
    """Вход моно 16k float32. Выход (моно float32, tgt_sr)."""
    out = []
    for s, e in split_silence(audio_16k):
        y = pipe.convert_chunk(
            pack["net"], 0, audio_16k[s:e], transpose,
            pack["index"], pack["index_vecs"], index_rate, protect,
            rms_mix_rate, pack["device"], pack["is_half"],
        )
        out.append(y)
    audio = np.concatenate(out).astype(np.float32)
    peak = np.abs(audio).max()
    if peak > 0.99:
        audio = audio / peak * 0.99
    return audio, pack["tgt_sr"]
