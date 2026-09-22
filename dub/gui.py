"""Shyni Dub GUI - окошко даббинга. Запуск: .\\.venv\\Scripts\\python.exe dub\\gui.py"""
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LANGS = ["auto", "ru", "en"]
DST_LANGS = ["en", "ru"]
SYNTH_LANGS = ["= dst", "Russian", "English"]


class DubGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Shyni Dub")
        root.geometry("620x520")
        self.job_q = queue.Queue()
        self.result_path = None

        import settings
        settings.init_settings()
        voices = ["orig"] + [r[0] for r in settings.list_base_voices()]

        f = ttk.Frame(root, padding=10)
        f.pack(fill="both", expand=True)

        # видео
        row = 0
        ttk.Label(f, text="Видео:").grid(row=row, column=0, sticky="w")
        self.video_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.video_var, width=55).grid(row=row, column=1, sticky="ew")
        ttk.Button(f, text="...", width=3, command=self.pick_video).grid(row=row, column=2)

        # режимы
        row = 1
        ttk.Label(f, text="Язык оригинала:").grid(row=row, column=0, sticky="w")
        self.src_var = tk.StringVar(value="auto")
        ttk.Combobox(f, textvariable=self.src_var, values=LANGS, state="readonly", width=10).grid(
            row=row, column=1, sticky="w")

        row = 2
        ttk.Label(f, text="Перевести на:").grid(row=row, column=0, sticky="w")
        self.dst_var = tk.StringVar(value="en")
        ttk.Combobox(f, textvariable=self.dst_var, values=DST_LANGS, state="readonly", width=10).grid(
            row=row, column=1, sticky="w")

        row = 3
        ttk.Label(f, text="Голос:").grid(row=row, column=0, sticky="w")
        self.voice_var = tk.StringVar(value="orig")
        ttk.Combobox(f, textvariable=self.voice_var, values=voices, state="readonly", width=20).grid(
            row=row, column=1, sticky="w")
        ttk.Label(f, text="orig = голос из видео").grid(row=row, column=2, sticky="w")

        row = 4
        ttk.Label(f, text="Язык синтеза:").grid(row=row, column=0, sticky="w")
        self.slang_var = tk.StringVar(value="= dst")
        ttk.Combobox(f, textvariable=self.slang_var, values=SYNTH_LANGS, state="readonly", width=10).grid(
            row=row, column=1, sticky="w")

        row = 5
        ttk.Label(f, text="Фон оригинала:").grid(row=row, column=0, sticky="w")
        self.bg_var = tk.DoubleVar(value=0.0)
        ttk.Scale(f, from_=0.0, to=0.5, variable=self.bg_var, length=200).grid(row=row, column=1, sticky="w")
        self.bg_lbl = ttk.Label(f, text="0.00")
        self.bg_lbl.grid(row=row, column=2, sticky="w")
        self.bg_var.trace_add("write", lambda *a: self.bg_lbl.config(text=f"{self.bg_var.get():.2f}"))

        # куда сохранить
        row = 6
        ttk.Label(f, text="Сохранить как:").grid(row=row, column=0, sticky="w")
        self.out_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.out_var, width=55).grid(row=row, column=1, sticky="ew")
        ttk.Button(f, text="...", width=3, command=self.pick_out).grid(row=row, column=2)

        # кнопки
        row = 7
        self.start_btn = ttk.Button(f, text="▶ Дублировать", command=self.start)
        self.start_btn.grid(row=row, column=0, columnspan=2, pady=8, sticky="ew")
        self.open_btn = ttk.Button(f, text="Открыть результат", command=self.open_result, state="disabled")
        self.open_btn.grid(row=row, column=2, pady=8)

        # лог
        row = 8
        self.log = tk.Text(f, height=14, state="disabled")
        self.log.grid(row=row, column=0, columnspan=3, sticky="nsew")
        f.rowconfigure(8, weight=1)
        f.columnconfigure(1, weight=1)

        self.root.after(200, self.poll_log)

    # ---------- ui helpers ----------

    def pick_video(self):
        p = filedialog.askopenfilename(filetypes=[("Видео", "*.mp4 *.mkv *.avi *.mov *.webm"), ("Все", "*.*")])
        if p:
            self.video_var.set(p)
            if not self.out_var.get():
                base, _ = os.path.splitext(p)
                self.out_var.set(base + "_dubbed.mp4")

    def pick_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4", "*.mp4")])
        if p:
            self.out_var.set(p)

    def append_log(self, msg: str):
        self.log.config(state="normal")
        self.log.insert("end", str(msg).encode("cp1251", "backslashreplace").decode("cp1251") + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def poll_log(self):
        try:
            while True:
                kind, payload = self.job_q.get_nowait()
                if kind == "log":
                    self.append_log(payload)
                elif kind == "done":
                    self.result_path = payload
                    self.start_btn.config(state="normal")
                    self.open_btn.config(state="normal" if payload else "disabled")
                    if payload:
                        messagebox.showinfo("Shyni Dub", f"Готово:\n{payload}")
                    else:
                        messagebox.showwarning("Shyni Dub", "Не получилось - смотри лог")
        except queue.Empty:
            pass
        self.root.after(200, self.poll_log)

    def open_result(self):
        if self.result_path and os.path.exists(self.result_path):
            os.startfile(self.result_path)

    # ---------- запуск ----------

    def start(self):
        video = self.video_var.get().strip()
        if not video or not os.path.exists(video):
            messagebox.showwarning("Shyni Dub", "Выбери видео")
            return
        slang = None if self.slang_var.get() == "= dst" else self.slang_var.get()
        job = {
            "input": video,
            "src": self.src_var.get(),
            "dst": self.dst_var.get(),
            "voice": self.voice_var.get(),
            "out": self.out_var.get().strip() or None,
            "bg": round(self.bg_var.get(), 2),
            "lang": slang,
        }
        self.start_btn.config(state="disabled")
        self.open_btn.config(state="disabled")
        self.result_path = None
        q = self.job_q

        def worker():
            try:
                import cli
                q.put(("log", f"[gui] старт: {os.path.basename(video)} -> {job['dst']}, голос {job['voice']}"))
                res = cli.run_job(job, log=lambda m: q.put(("log", m)))
                q.put(("done", res))
            except Exception as e:  # noqa: BLE001
                import traceback
                q.put(("log", f"[gui] ОШИБКА: {type(e).__name__}: {e}"))
                q.put(("log", traceback.format_exc(limit=3)))
                q.put(("done", None))

        threading.Thread(target=worker, daemon=True).start()


def main():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    DubGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
