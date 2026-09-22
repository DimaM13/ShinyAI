"""A/B тест ICL vs x-vector. Разовый скрипт, дефолты не меняет."""
import time
import soundfile as sf
import tts_voice
import config

TEXT = "Привет! Я Шайни, послушай мой голос внимательно и скажи, какой вариант звучит лучше!"

m = tts_voice.get_model()

t0 = time.time()
p_icl = m.create_voice_clone_prompt(ref_audio=config.REF_AUDIO, ref_text=config.REF_TEXT)
w, sr = m.generate_voice_clone(text=tts_voice.clean_for_tts(TEXT), language="Russian", voice_clone_prompt=p_icl)
sf.write("test_AB_ICL.wav", w[0], sr)
print("ICL done", round(time.time() - t0, 1), flush=True)

t0 = time.time()
p_xv = m.create_voice_clone_prompt(ref_audio=config.REF_AUDIO, x_vector_only_mode=True)
w, sr = m.generate_voice_clone(text=tts_voice.clean_for_tts(TEXT), language="Russian", voice_clone_prompt=p_xv)
sf.write("test_AB_XVEC.wav", w[0], sr)
print("XVEC done", round(time.time() - t0, 1), flush=True)
