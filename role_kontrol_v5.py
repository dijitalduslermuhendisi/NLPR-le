import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
import serial
import serial.tools.list_ports
import threading
import time
import random
import json
import os
import datetime
import pyttsx3

HAS_SPEECH = False
sr = None
try:
    import speech_recognition as _sr
    import pyaudio
    sr = _sr
    HAS_SPEECH = True
except ImportError:
    print("⚠️ PyAudio yok → sesli komut devre dışı")

# ╔══════════════════════════════════╗
# ║   KULLANICI TANIMLI NLP MOTORU   ║
# ╚══════════════════════════════════╝

COMMANDS_FILE = "voice_commands.json"

DEFAULT_INTENTS = {
    "ON": [
        "aç", "yak", "açık", "on", "çalıştır", "başlat", "aktif",
        "devreye", "tetikle", "enable", "start", "güç ver", "enerji",
        "etkinleştir", "yandır", "aydınlat", "power on", "turn on",
        "ışığı aç", "lambayı yak", "röleyi aç", "sistemi başlat",
        "elektrikleri aç", "hadi aç", "lütfen aç"
    ],
    "OFF": [
        "kapat", "kapa", "söndür", "off", "durdur", "kapalı",
        "devre dışı", "kes", "bitir", "disable", "power off", "turn off",
        "ışığı kapat", "lambayı söndür", "röleyi kapat", "sistemi durdur",
        "elektrikleri kes", "karanlık", "hadi kapat", "lütfen kapat"
    ],
    "TOGGLE": [
        "değiştir", "toggle", "tersine", "tam tersi", "switch",
        "çevir", "diğerine geç", "durumu değiştir"
    ],
    "STATUS": [
        "durum", "status", "nasıl", "bilgi", "kontrol", "nedir",
        "ne durumda", "açık mı", "kapalı mı", "sorgula"
    ]
}

INTENT_TR = {"ON": "aç", "OFF": "kapat", "TOGGLE": "toggle", "STATUS": "durum"}
INTENT_FROM_TR = {"AÇ": "ON", "KAPAT": "OFF", "TOGGLE": "TOGGLE", "DURUM": "STATUS"}


def load_commands():
    if os.path.exists(COMMANDS_FILE):
        try:
            with open(COMMANDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            result = {}
            for intent in DEFAULT_INTENTS:
                result[intent] = list(data.get(intent, DEFAULT_INTENTS[intent]))
            return result
        except Exception:
            pass
    defaults = {k: list(v) for k, v in DEFAULT_INTENTS.items()}
    try:
        with open(COMMANDS_FILE, "w", encoding="utf-8") as f:
            json.dump(defaults, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return defaults


def save_commands():
    try:
        with open(COMMANDS_FILE, "w", encoding="utf-8") as f:
            json.dump(INTENTS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


INTENTS = load_commands()


def extract_intent(text: str):
    text = text.lower().strip()
    scores = {k: 0 for k in INTENTS}
    for intent, keywords in INTENTS.items():
        for kw in keywords:
            if kw in text:
                scores[intent] += len(kw)
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        total = sum(scores.values()) or 1
        confidence = int((scores[best] / total) * 100)
        return best, confidence
    return None, 0


# ╔══════════════════════════════════╗
# ║          SES MOTORU              ║
# ╚══════════════════════════════════╝

TTS_ENABLED = True
tts_engine = None
tts_lock = threading.Lock()
try:
    tts_engine = pyttsx3.init()
    tts_engine.setProperty("rate", 165)
    tts_engine.setProperty("volume", 1.0)
    for v in tts_engine.getProperty("voices"):
        if "turkish" in v.name.lower() or "tr" in v.id.lower():
            tts_engine.setProperty("voice", v.id)
            break
except Exception:
    pass


def speak(text):
    if not TTS_ENABLED:
        return

    def _s():
        with tts_lock:
            if tts_engine:
                try:
                    tts_engine.say(text)
                    tts_engine.runAndWait()
                except Exception:
                    pass
    threading.Thread(target=_s, daemon=True).start()


# ╔══════════════════════════════════╗
# ║        RENK PALETİ              ║
# ╚══════════════════════════════════╝

C = {
    "bg": "#07070c", "card": "#101018", "card2": "#161622", "surface": "#1c1c2a",
    "green": "#00ffa3", "red": "#ff3b5c", "blue": "#5b8cff", "purple": "#b084ff",
    "orange": "#ff9f43", "yellow": "#ffd60a", "text": "#eef0fa",
    "text2": "#5e5e78", "border": "#20202e",
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb2hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def _lerp(c1, c2, t):
    r1, g1, b1 = _hex2rgb(c1)
    r2, g2, b2 = _hex2rgb(c2)
    return _rgb2hex((r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t))


# ╔══════════════════════════════════════════════════════╗
# ║                   ANA UYGULAMA                      ║
# ╚══════════════════════════════════════════════════════╝

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("⚡ RELAY AI")
        self.geometry("680x1040")
        self.minsize(600, 860)
        self.configure(fg_color=C["bg"])

        self.ser = None
        self.relay = False
        self.connected = False
        self.listening = False
        self.continuous_mode = False
        self.continuous_stop = threading.Event()
        self.cmd_count = 0
        self.uptime_start = time.time()
        self._alive = True
        self._toasts = []

        self.settings = {"lang": "tr-TR", "tts_enabled": True, "tts_rate": 165, "baud": 9600}

        # Orb animasyon durumları
        self._orb_angle = 0
        self._disp_color = C["text2"]
        self._stars = []

        # Orb etkileşim durumları (YENİ)
        self._orb_hover = False
        self._orb_press_active = False
        self._orb_press_start = None
        self._orb_press_token = 0
        self._orb_long_press_triggered = False
        self.ORB_LONG_PRESS = 0.8  # saniye
        self._orb_flash_color = None
        self._orb_flash_start = 0
        self._orb_flash_duration = 0.45

        self._eq_levels = [0.15] * 9

        self.rec = None
        self.mic = None
        if HAS_SPEECH:
            self.rec = sr.Recognizer()
            self.rec.pause_threshold = 2.0
            self.rec.phrase_threshold = 0.3
            self.rec.non_speaking_duration = 1.5
            try:
                self.mic = sr.Microphone()
            except Exception:
                pass

        self._build_ui()
        self._bind_shortcuts()
        self._refresh_ports()
        self._tick()
        self._animate_orb()
        self._animate_voice_orb()
        self.after(100, self._show_boot_splash)
        self.protocol("WM_DELETE_WINDOW", self._quit)

    # ════════════════════════════════════════
    #            BOOT SPLASH
    # ════════════════════════════════════════

    def _show_boot_splash(self):
        splash = ctk.CTkFrame(self, fg_color=C["bg"])
        splash.place(relx=0, rely=0, relwidth=1, relheight=1)

        ctk.CTkLabel(splash, text="⚡", font=ctk.CTkFont(size=46),
                     text_color=C["green"]).place(relx=0.5, rely=0.42, anchor="center")
        ctk.CTkLabel(splash, text="RELAY A.I.",
                     font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
                     text_color=C["text"]).place(relx=0.5, rely=0.50, anchor="center")

        sub = ctk.CTkLabel(splash, text="başlatılıyor...",
                            font=ctk.CTkFont(family="Cascadia Code", size=12),
                            text_color=C["text2"])
        sub.place(relx=0.5, rely=0.57, anchor="center")

        total_words = sum(len(v) for v in INTENTS.values())
        steps = [
            "çekirdek modülleri yükleniyor",
            f"{total_words} komut kelimesi yüklendi",
            f"ses modülleri: {'bulundu' if HAS_SPEECH else 'bulunamadı'}",
            "arayüz render ediliyor",
            "sistem hazır"
        ]

        def _step(i=0):
            if not self._alive:
                return
            if i < len(steps):
                sub.configure(text=steps[i] + "...")
                self.after(260, lambda: _step(i + 1))
            else:
                self.after(300, splash.destroy)
        _step()

    # ════════════════════════════════════════
    #               ARAYÜZ
    # ════════════════════════════════════════

    def _build_ui(self):

        wrap = ctk.CTkScrollableFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True)

        outer = ctk.CTkFrame(wrap, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=26, pady=20)

        # ── HEADER ──
        header = ctk.CTkFrame(outer, fg_color="transparent")
        header.pack(fill="x", pady=(0, 18))

        head_left = ctk.CTkFrame(header, fg_color="transparent")
        head_left.pack(side="left")

        ctk.CTkLabel(head_left, text="RELAY A.I.",
                     font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"),
                     text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(head_left, text="akıllı kontrol sistemi",
                     font=ctk.CTkFont(size=11), text_color=C["text2"]).pack(anchor="w")

        head_right = ctk.CTkFrame(header, fg_color="transparent")
        head_right.pack(side="right")

        top_right_row = ctk.CTkFrame(head_right, fg_color="transparent")
        top_right_row.pack(anchor="e")

        self.clock_lbl = ctk.CTkLabel(top_right_row, text="",
                                       font=ctk.CTkFont(family="Cascadia Code", size=12),
                                       text_color=C["text2"])
        self.clock_lbl.pack(side="left", padx=(0, 8))

        ctk.CTkButton(top_right_row, text="⚙", width=28, height=28,
                      font=ctk.CTkFont(size=14), fg_color=C["surface"],
                      hover_color=C["border"], corner_radius=8,
                      command=self._open_settings).pack(side="left")

        status_row = ctk.CTkFrame(head_right, fg_color="transparent")
        status_row.pack(anchor="e", pady=(2, 0))

        self.conn_dot = ctk.CTkLabel(status_row, text="●", font=ctk.CTkFont(size=12),
                                      text_color=C["red"])
        self.conn_dot.pack(side="left", padx=(0, 4))

        self.conn_txt = ctk.CTkLabel(status_row, text="bağlı değil",
                                      font=ctk.CTkFont(size=11), text_color=C["text2"])
        self.conn_txt.pack(side="left")

        self.uptime_lbl = ctk.CTkLabel(head_right, text="⏱ 00:00:00  ·  0 komut",
                                        font=ctk.CTkFont(family="Cascadia Code", size=10),
                                        text_color=C["text2"])
        self.uptime_lbl.pack(anchor="e", pady=(2, 0))

        # ── BAĞLANTI PANELİ ──
        conn = ctk.CTkFrame(outer, fg_color=C["card"], corner_radius=16, height=52)
        conn.pack(fill="x", pady=(0, 16))
        conn.pack_propagate(False)

        inner_conn = ctk.CTkFrame(conn, fg_color="transparent")
        inner_conn.pack(fill="both", expand=True, padx=12, pady=8)

        self.port_cb = ctk.CTkComboBox(inner_conn, width=130, height=32, state="readonly",
                                        font=ctk.CTkFont(size=12), border_color=C["border"],
                                        fg_color=C["surface"], button_color=C["surface"],
                                        button_hover_color=C["border"], dropdown_fg_color=C["card2"])
        self.port_cb.pack(side="left", padx=(0, 6))

        ctk.CTkButton(inner_conn, text="↻", width=32, height=32,
                      font=ctk.CTkFont(size=14), fg_color=C["surface"],
                      hover_color=C["border"], corner_radius=8,
                      command=self._refresh_ports).pack(side="left", padx=(0, 6))

        self.conn_btn = ctk.CTkButton(inner_conn, text="BAĞLAN", width=100, height=32,
                                       font=ctk.CTkFont(size=11, weight="bold"),
                                       fg_color=C["green"], hover_color="#00c278",
                                       text_color="#000", corner_radius=8,
                                       command=self._toggle_conn)
        self.conn_btn.pack(side="right")

        # ── MERKEZ GÜÇ ORBU (FONKSİYONEL) ──
        orb_card = ctk.CTkFrame(outer, fg_color=C["card"], corner_radius=24)
        orb_card.pack(fill="x", pady=(0, 16))

        orb_inner = ctk.CTkFrame(orb_card, fg_color="transparent")
        orb_inner.pack(pady=(22, 10))

        self.orb_size = 230
        self.orb_canvas = tk.Canvas(orb_inner, width=self.orb_size, height=self.orb_size,
                                     bg=C["card"], highlightthickness=0, bd=0)
        self.orb_canvas.pack()
        self.orb_canvas.configure(cursor="hand2")

        # ── Orb etkileşim bağlamaları ──
        self.orb_canvas.bind("<ButtonPress-1>", self._orb_press)
        self.orb_canvas.bind("<ButtonRelease-1>", self._orb_release)
        self.orb_canvas.bind("<Enter>", self._orb_enter)
        self.orb_canvas.bind("<Leave>", self._orb_leave)
        self.orb_canvas.bind("<Button-3>", self._orb_right_click)
        self.orb_canvas.bind("<Button-2>", self._orb_middle_click)

        self._stars = [
            {"x": random.uniform(10, self.orb_size - 10), "y": random.uniform(10, self.orb_size - 10),
             "spd": random.uniform(0.05, 0.25), "r": random.uniform(0.6, 1.6)}
            for _ in range(16)
        ]

        self.orb_sub = ctk.CTkLabel(orb_card, text="pin 3 · low",
                                     font=ctk.CTkFont(family="Cascadia Code", size=11),
                                     text_color=C["text2"])
        self.orb_sub.pack(pady=(0, 4))

        ctk.CTkLabel(
            orb_card,
            text="tıkla: toggle  ·  basılı tut: sesli komut  ·  sağ tık: durum  ·  orta tık/ctrl+tık: acil kapat",
            font=ctk.CTkFont(size=9), text_color=C["text2"], wraplength=440, justify="center"
        ).pack(pady=(0, 16))

        # ── HIZLI KOMUT BUTONLARI ──
        btn_row = ctk.CTkFrame(outer, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 16))
        for col in range(3):
            btn_row.columnconfigure(col, weight=1)

        ctk.CTkButton(btn_row, text="AÇ", height=44, font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=C["surface"], hover_color=C["green"], text_color=C["green"],
                      corner_radius=12, border_width=1, border_color=C["border"],
                      command=lambda: self._cmd("ON")).grid(row=0, column=0, padx=(0, 5), sticky="ew")

        ctk.CTkButton(btn_row, text="KAPAT", height=44, font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=C["surface"], hover_color=C["red"], text_color=C["red"],
                      corner_radius=12, border_width=1, border_color=C["border"],
                      command=lambda: self._cmd("OFF")).grid(row=0, column=1, padx=5, sticky="ew")

        ctk.CTkButton(btn_row, text="TOGGLE", height=44, font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=C["surface"], hover_color=C["blue"], text_color=C["blue"],
                      corner_radius=12, border_width=1, border_color=C["border"],
                      command=lambda: self._cmd("TOGGLE")).grid(row=0, column=2, padx=(5, 0), sticky="ew")

        # ── SES BÖLÜMÜ ──
        voice_card = ctk.CTkFrame(outer, fg_color=C["card"], corner_radius=20)
        voice_card.pack(fill="x", pady=(0, 16))

        voice_top = ctk.CTkFrame(voice_card, fg_color="transparent")
        voice_top.pack(fill="x", padx=18, pady=(16, 6))

        voice_left = ctk.CTkFrame(voice_top, fg_color="transparent")
        voice_left.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(voice_left, text="SESLİ KOMUT", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text"]).pack(anchor="w")

        self.voice_status = ctk.CTkLabel(voice_left, text="hazır" if HAS_SPEECH else "pyaudio gerekli",
                                          font=ctk.CTkFont(size=11), text_color=C["text2"])
        self.voice_status.pack(anchor="w")

        self.cont_btn = ctk.CTkButton(voice_top, text="∞ SÜREKLİ", width=100, height=34,
                                       font=ctk.CTkFont(size=11, weight="bold"),
                                       fg_color=C["surface"], hover_color=C["border"],
                                       text_color=C["text2"], corner_radius=17,
                                       border_width=1, border_color=C["border"],
                                       state="normal" if (HAS_SPEECH and self.mic) else "disabled",
                                       command=self._toggle_continuous)
        self.cont_btn.pack(side="right")

        self.voice_size = 90
        self.voice_canvas = tk.Canvas(voice_card, width=220, height=self.voice_size,
                                       bg=C["card"], highlightthickness=0, bd=0)
        self.voice_canvas.pack(pady=(4, 6))
        if HAS_SPEECH and self.mic:
            self.voice_canvas.configure(cursor="hand2")
            self.voice_canvas.bind("<Button-1>", lambda e: self._single_listen())

        self.voice_result = ctk.CTkLabel(voice_card, text="", font=ctk.CTkFont(size=12),
                                          text_color=C["blue"], wraplength=480)
        self.voice_result.pack(padx=18, pady=(0, 16))

        # ── 🗣️ KULLANICI TANIMLI KOMUT KELİMELERİ ──
        cmd_card = ctk.CTkFrame(outer, fg_color=C["card"], corner_radius=20)
        cmd_card.pack(fill="x", pady=(0, 16))

        cmd_top = ctk.CTkFrame(cmd_card, fg_color="transparent")
        cmd_top.pack(fill="x", padx=18, pady=(16, 6))

        cmd_left = ctk.CTkFrame(cmd_top, fg_color="transparent")
        cmd_left.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(cmd_left, text="🗣️ KOMUT KELİMELERİM",
                     font=ctk.CTkFont(size=12, weight="bold"), text_color=C["text"]).pack(anchor="w")

        self.cmd_count_lbl = ctk.CTkLabel(cmd_left, text="", font=ctk.CTkFont(size=10),
                                           text_color=C["text2"])
        self.cmd_count_lbl.pack(anchor="w")

        ctk.CTkButton(cmd_top, text="tümünü yönet", width=110, height=30,
                      font=ctk.CTkFont(size=11), fg_color=C["surface"],
                      hover_color=C["border"], text_color=C["text2"], corner_radius=15,
                      command=self._open_command_manager).pack(side="right")

        ctk.CTkLabel(cmd_card,
                     text='örnek: "hadi parlat" yazıp AÇ kategorisine ekle → röleyi böyle de açabilirsin',
                     font=ctk.CTkFont(size=10), text_color=C["text2"],
                     wraplength=560, justify="left").pack(anchor="w", padx=18)

        add_row = ctk.CTkFrame(cmd_card, fg_color="transparent")
        add_row.pack(fill="x", padx=18, pady=(8, 16))

        self.cmd_intent_cb = ctk.CTkComboBox(add_row, width=110, height=36, state="readonly",
                                              values=["AÇ", "KAPAT", "TOGGLE", "DURUM"],
                                              fg_color=C["surface"], button_color=C["surface"],
                                              dropdown_fg_color=C["card2"], font=ctk.CTkFont(size=12))
        self.cmd_intent_cb.set("AÇ")
        self.cmd_intent_cb.pack(side="left", padx=(0, 6))

        self.cmd_word_entry = ctk.CTkEntry(add_row, placeholder_text="kendi kelimeni yaz...",
                                            height=36, fg_color=C["surface"], border_color=C["border"],
                                            corner_radius=10, font=ctk.CTkFont(size=12))
        self.cmd_word_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.cmd_word_entry.bind("<Return>", lambda e: self._quick_add_command())

        ctk.CTkButton(add_row, text="+", width=36, height=36, font=ctk.CTkFont(size=16, weight="bold"),
                      fg_color=C["green"], hover_color="#00c278", text_color="#000",
                      corner_radius=10, command=self._quick_add_command).pack(side="right")

        self._refresh_cmd_counts()

        # ── YAZILI KOMUT ──
        text_card = ctk.CTkFrame(outer, fg_color=C["card"], corner_radius=20)
        text_card.pack(fill="x", pady=(0, 16))

        text_inner = ctk.CTkFrame(text_card, fg_color="transparent")
        text_inner.pack(fill="x", padx=16, pady=(16, 8))

        self.entry = ctk.CTkEntry(text_inner, placeholder_text="komut yaz... (ışığı aç, söndür, durum...)",
                                   height=42, font=ctk.CTkFont(size=13), border_color=C["border"],
                                   fg_color=C["surface"], corner_radius=12)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self._text_cmd())

        ctk.CTkButton(text_inner, text="➤", width=42, height=42, font=ctk.CTkFont(size=16, weight="bold"),
                      fg_color=C["blue"], hover_color="#4a7ae6", corner_radius=12,
                      command=self._text_cmd).pack(side="right")

        chip_row = ctk.CTkFrame(text_card, fg_color="transparent")
        chip_row.pack(fill="x", padx=16, pady=(0, 6))
        for phrase in ["ışığı aç", "kapat", "durum nedir", "toggle yap"]:
            ctk.CTkButton(chip_row, text=phrase, height=26, font=ctk.CTkFont(size=10),
                          fg_color=C["surface"], hover_color=C["border"], text_color=C["text2"],
                          corner_radius=13, command=lambda p=phrase: self._quick_fill(p)
                          ).pack(side="left", padx=(0, 6))

        self.nlp_lbl = ctk.CTkLabel(text_card, text="", font=ctk.CTkFont(size=10), text_color=C["text2"])
        self.nlp_lbl.pack(padx=18, pady=(0, 12))

        # ── LOG ──
        log_card = ctk.CTkFrame(outer, fg_color=C["card"], corner_radius=20)
        log_card.pack(fill="both", expand=True)

        log_header = ctk.CTkFrame(log_card, fg_color="transparent")
        log_header.pack(fill="x", padx=16, pady=(14, 6))

        ctk.CTkLabel(log_header, text="SİSTEM GÜNLÜĞÜ", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text"]).pack(side="left")

        ctk.CTkButton(log_header, text="temizle", width=60, height=24, font=ctk.CTkFont(size=10),
                      fg_color=C["surface"], hover_color=C["red"], corner_radius=8,
                      command=self._clear_log).pack(side="right")

        self.log = ctk.CTkTextbox(log_card, height=160, font=ctk.CTkFont(family="Cascadia Code", size=11),
                                   fg_color=C["bg"], text_color=C["text2"], border_width=0,
                                   corner_radius=14, state="disabled")
        self.log.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self._log("sistem başlatıldı")
        self._log(f"ses: {'aktif' if HAS_SPEECH else 'devre dışı'}")
        self._log(f"komut kelimeleri yüklendi: {sum(len(v) for v in INTENTS.values())} toplam")

    # ════════════════════════════════════════
    #        ORB ETKİLEŞİM FONKSİYONLARI (YENİ)
    # ════════════════════════════════════════

    def _orb_enter(self, event):
        self._orb_hover = True

    def _orb_leave(self, event):
        self._orb_hover = False
        if self._orb_press_active:
            self._orb_press_active = False
            self._orb_press_start = None

    def _orb_press(self, event):
        self._orb_press_active = True
        self._orb_long_press_triggered = False
        self._orb_press_start = time.time()
        self._orb_press_token += 1
        token = self._orb_press_token
        self.after(int(self.ORB_LONG_PRESS * 1000), lambda: self._check_long_press(token))

    def _check_long_press(self, token):
        if (self._orb_press_active and token == self._orb_press_token
                and self._orb_press_start is not None):
            self._orb_long_press_triggered = True
            self._orb_press_active = False
            self._orb_press_start = None
            self._orb_flash("voice")
            self._log("🎯 orb uzun basma → sesli komut")
            self._single_listen()

    def _orb_release(self, event):
        ctrl_pressed = bool(event.state & 0x0004)
        if self._orb_press_active and not self._orb_long_press_triggered:
            elapsed = time.time() - (self._orb_press_start or time.time())
            if elapsed < self.ORB_LONG_PRESS:
                if ctrl_pressed:
                    self._cmd("OFF", "orb-acil")
                else:
                    self._cmd("TOGGLE", "orb")
        self._orb_press_active = False
        self._orb_press_start = None

    def _orb_right_click(self, event):
        self._cmd("STATUS", "orb-sağtık")

    def _orb_middle_click(self, event):
        self._cmd("OFF", "orb-ortatık")

    def _orb_flash(self, kind):
        color_map = {
            "success": C["green"], "off": C["red"], "info": C["blue"],
            "voice": C["purple"], "error": C["red"], "warning": C["orange"],
        }
        self._orb_flash_color = color_map.get(kind, C["blue"])
        self._orb_flash_start = time.time()

    # ════════════════════════════════════════
    #    KULLANICI TANIMLI KOMUT KELİMELERİ
    # ════════════════════════════════════════

    def _refresh_cmd_counts(self):
        txt = " · ".join(f"{INTENT_TR[k]}: {len(v)}" for k, v in INTENTS.items())
        self.cmd_count_lbl.configure(text=txt)

    def _quick_add_command(self):
        label = self.cmd_intent_cb.get()
        intent = INTENT_FROM_TR.get(label)
        word = self.cmd_word_entry.get().strip().lower()
        if not word or not intent:
            return
        for other_intent, words in INTENTS.items():
            if word in words:
                if other_intent == intent:
                    self._toast("bu kelime zaten ekli", "warning")
                else:
                    self._toast(f"'{word}' zaten {INTENT_TR[other_intent]} kategorisinde", "warning")
                return
        INTENTS[intent].append(word)
        save_commands()
        self.cmd_word_entry.delete(0, "end")
        self._log(f"+ '{word}' → {INTENT_TR[intent]} komutuna eklendi")
        self._toast(f"'{word}' eklendi → {INTENT_TR[intent]}", "success")
        self._refresh_cmd_counts()

    def _open_command_manager(self):
        win = ctk.CTkToplevel(self)
        win.title("🗣️ Komut Kelimelerim")
        win.geometry("540x640")
        win.configure(fg_color=C["card"])
        win.attributes("-topmost", True)
        win.grab_set()

        ctk.CTkLabel(win, text="🗣️ SESLİ KOMUT KELİMELERİM",
                     font=ctk.CTkFont(size=16, weight="bold"), text_color=C["text"]).pack(pady=(18, 2))
        ctk.CTkLabel(win, text="her kategori için istediğin kelimeleri ekle veya sil",
                     font=ctk.CTkFont(size=11), text_color=C["text2"]).pack(pady=(0, 14))

        tabview = ctk.CTkTabview(
            win, fg_color=C["card2"],
            segmented_button_fg_color=C["surface"],
            segmented_button_selected_color=C["blue"],
            segmented_button_unselected_color=C["surface"],
            text_color=C["text"]
        )
        tabview.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        labels = {"ON": "AÇ 🟢", "OFF": "KAPAT 🔴", "TOGGLE": "TOGGLE 🔵", "STATUS": "DURUM ⚪"}
        for intent in INTENTS:
            tab = tabview.add(labels.get(intent, intent))
            self._build_intent_tab(tab, intent)

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 18))

        def _reopen():
            win.destroy()
            self._open_command_manager()

        ctk.CTkButton(btn_row, text="📤 dışa aktar", height=34, fg_color=C["surface"],
                      hover_color=C["border"], command=self._export_commands
                      ).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(btn_row, text="📥 içe aktar", height=34, fg_color=C["surface"],
                      hover_color=C["border"], command=lambda: (self._import_commands(), _reopen())
                      ).pack(side="left", expand=True, fill="x", padx=4)
        ctk.CTkButton(btn_row, text="♻ sıfırla", height=34, fg_color=C["surface"],
                      hover_color=C["red"], command=lambda: (self._reset_all_commands(), _reopen())
                      ).pack(side="left", expand=True, fill="x", padx=(4, 0))

    def _build_intent_tab(self, parent, intent):
        count_lbl = ctk.CTkLabel(parent, text=f"{len(INTENTS[intent])} kelime",
                                  font=ctk.CTkFont(size=10), text_color=C["text2"])
        count_lbl.pack(anchor="w", padx=4, pady=(6, 4))

        scroll = ctk.CTkScrollableFrame(parent, fg_color=C["surface"], height=260, corner_radius=10)
        scroll.pack(fill="both", expand=True, padx=4, pady=(0, 8))

        add_row = ctk.CTkFrame(parent, fg_color="transparent")
        add_row.pack(fill="x", padx=4, pady=(0, 6))

        entry = ctk.CTkEntry(add_row, placeholder_text="yeni kelime/ifade ekle...",
                              fg_color=C["card2"], border_color=C["border"], height=34)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def _refresh():
            for w in scroll.winfo_children():
                w.destroy()
            for kw in sorted(INTENTS[intent]):
                row = ctk.CTkFrame(scroll, fg_color=C["card2"], corner_radius=8)
                row.pack(fill="x", pady=2, padx=2)
                ctk.CTkLabel(row, text=kw, font=ctk.CTkFont(size=12),
                             text_color=C["text"]).pack(side="left", padx=10, pady=6)
                ctk.CTkButton(row, text="✕", width=26, height=26, fg_color="transparent",
                              hover_color=C["red"], text_color=C["text2"], corner_radius=13,
                              command=lambda k=kw: _remove(k)).pack(side="right", padx=6, pady=4)
            count_lbl.configure(text=f"{len(INTENTS[intent])} kelime")

        def _add():
            txt = entry.get().strip().lower()
            if not txt:
                return
            for other_intent, words in INTENTS.items():
                if txt in words:
                    if other_intent == intent:
                        self._toast("bu kelime zaten var", "warning")
                    else:
                        self._toast(f"'{txt}' zaten {INTENT_TR[other_intent]} kategorisinde", "warning")
                    return
            INTENTS[intent].append(txt)
            save_commands()
            entry.delete(0, "end")
            _refresh()
            self._refresh_cmd_counts()
            self._log(f"+ '{txt}' → {intent} kategorisine eklendi")
            self._toast(f"'{txt}' eklendi", "success")

        def _remove(kw):
            if kw in INTENTS[intent]:
                INTENTS[intent].remove(kw)
                save_commands()
                _refresh()
                self._refresh_cmd_counts()
                self._log(f"- '{kw}' → {intent} kategorisinden silindi")

        entry.bind("<Return>", lambda e: _add())
        ctk.CTkButton(add_row, text="ekle", width=60, height=34, fg_color=C["blue"],
                      hover_color="#4a7ae6", command=_add).pack(side="right")

        _refresh()

    def _reset_all_commands(self):
        global INTENTS
        INTENTS = {k: list(v) for k, v in DEFAULT_INTENTS.items()}
        save_commands()
        self._refresh_cmd_counts()
        self._log("♻ komut kelimeleri varsayılana sıfırlandı")
        self._toast("varsayılana sıfırlandı", "info")

    def _export_commands(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                             filetypes=[("JSON", "*.json")],
                                             initialfile="komutlarim.json")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(INTENTS, f, ensure_ascii=False, indent=2)
            self._log(f"📤 komutlar dışa aktarıldı: {path}")
            self._toast("dışa aktarıldı", "success")
        except Exception:
            self._toast("dışa aktarma hatası", "error")

    def _import_commands(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for intent in INTENTS:
                if intent in data and isinstance(data[intent], list):
                    INTENTS[intent] = sorted(set(INTENTS[intent]) | set(data[intent]))
            save_commands()
            self._refresh_cmd_counts()
            self._log(f"📥 komutlar içe aktarıldı: {path}")
            self._toast("içe aktarıldı", "success")
        except Exception:
            self._toast("içe aktarma hatası", "error")

    # ════════════════════════════════════════
    #         KLAVYE KISAYOLLARI
    # ════════════════════════════════════════

    def _bind_shortcuts(self):
        self.bind("<space>", self._on_space)
        self.bind("<Control-m>", lambda e: self._single_listen())
        self.bind("<Control-M>", lambda e: self._single_listen())
        self.bind("<Escape>", lambda e: self._stop_continuous() if self.continuous_mode else None)
        self.bind("<Control-l>", lambda e: self._clear_log())
        self.bind("<Control-L>", lambda e: self._clear_log())

    def _on_space(self, event):
        widget = self.focus_get()
        if isinstance(widget, (ctk.CTkEntry, tk.Entry)):
            return
        self._cmd("TOGGLE", "klavye")
        return "break"

    def _quick_fill(self, phrase):
        self.entry.delete(0, "end")
        self.entry.insert(0, phrase)
        self._text_cmd()

    # ════════════════════════════════════════
    #        CANVAS ANİMASYONLARI
    # ════════════════════════════════════════

    def _animate_orb(self):
        if not self._alive:
            return
        try:
            c = self.orb_canvas
            c.delete("all")
            size = self.orb_size
            cx = cy = size / 2

            target = C["green"] if self.relay else (C["red"] if self.connected else C["text2"])
            self._disp_color = _lerp(self._disp_color, target, 0.12)
            base = self._disp_color
            intensity = 0.5 if self.relay else (0.14 if self.connected else 0.05)
            if self._orb_hover:
                intensity = min(1.0, intensity * 1.35)

            # yıldızlar
            for s in self._stars:
                s["y"] += s["spd"]
                if s["y"] > size:
                    s["y"] = 0
                    s["x"] = random.uniform(10, size - 10)
                c.create_oval(s["x"] - s["r"], s["y"] - s["r"], s["x"] + s["r"], s["y"] + s["r"],
                              outline="", fill=C["border"])

            # glow halkaları
            for i in range(7, 0, -1):
                r = 58 + i * 9
                t = i / 7
                col = _lerp(C["card"], base, intensity * (1 - t) + 0.02)
                c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="", fill=col)

            # dönen yaylar
            ring_r = 92
            width = 4 if self.connected else 2
            if self._orb_hover:
                width += 1
            for k in range(3):
                start = (self._orb_angle + k * 120) % 360
                c.create_arc(cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r,
                              start=start, extent=46, style="arc", outline=base, width=width)

            # uzun-basma ilerleme halkası
            if self._orb_press_active and self._orb_press_start and not self._orb_long_press_triggered:
                elapsed = time.time() - self._orb_press_start
                progress = min(1.0, elapsed / self.ORB_LONG_PRESS)
                prog_r = ring_r + 14
                c.create_arc(cx - prog_r, cy - prog_r, cx + prog_r, cy + prog_r,
                              start=90, extent=-360 * progress, style="arc",
                              outline=C["purple"], width=3)
                if progress > 0.05:
                    c.create_text(cx, cy + size / 2 - 14, text="sesli komut için tutun...",
                                  font=("Segoe UI", 8), fill=C["purple"])

            c.create_oval(cx - 70, cy - 70, cx + 70, cy + 70, outline=C["border"], width=1)

            # merkez disk (basınca hafif küçülür)
            press_scale = 0.94 if (self._orb_press_active and not self._orb_long_press_triggered) else 1.0
            inner_r = 64 * press_scale
            c.create_oval(cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r,
                           outline=base, width=2, fill=C["card2"])

            c.create_text(cx, cy - 10, text="⏻", font=("Segoe UI", int(34 * press_scale), "bold"), fill=base)
            c.create_text(cx, cy + 28, text=("AÇIK" if self.relay else "KAPALI"),
                           font=("Segoe UI", 13, "bold"), fill=base)

            # HUD köşe işaretleri
            m, br = 14, 16
            for (x0, y0, dx, dy) in [(m, m, 1, 1), (size - m, m, -1, 1),
                                      (m, size - m, 1, -1), (size - m, size - m, -1, -1)]:
                c.create_line(x0, y0, x0 + br * dx, y0, fill=C["border"], width=2)
                c.create_line(x0, y0, x0, y0 + br * dy, fill=C["border"], width=2)

            # komut sonucu flaş halkası (en üstte)
            if self._orb_flash_color:
                elapsed = time.time() - self._orb_flash_start
                dur = self._orb_flash_duration
                if elapsed < dur:
                    t = elapsed / dur
                    radius = 66 + t * 50
                    fade_color = _lerp(self._orb_flash_color, C["card"], t)
                    w = max(1, int(4 * (1 - t)))
                    c.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                                  outline=fade_color, width=w)
                else:
                    self._orb_flash_color = None

            speed = 3 if self.relay else 1.2
            self._orb_angle = (self._orb_angle + speed) % 360

            now = datetime.datetime.now().strftime("%H:%M:%S")
            self.orb_sub.configure(text=f"pin 3 · {'high' if self.relay else 'low'} · {now}")
        except Exception:
            pass
        self.after(40, self._animate_orb)

    def _animate_voice_orb(self):
        if not self._alive:
            return
        try:
            c = self.voice_canvas
            c.delete("all")
            w, h = 220, self.voice_size
            bars = len(self._eq_levels)
            gap = 5
            bar_w = (w - gap * (bars + 1)) / bars
            base_color = C["red"] if self.listening else C["purple"]

            for i in range(bars):
                if self.listening:
                    target = random.uniform(0.2, 1.0)
                    self._eq_levels[i] += (target - self._eq_levels[i]) * 0.35
                else:
                    t = time.time() * 2 + i
                    target = 0.12 + 0.05 * abs(((t % 2) - 1))
                    self._eq_levels[i] += (target - self._eq_levels[i]) * 0.08

                level = max(0.05, min(1.0, self._eq_levels[i]))
                bh = level * (h - 20)
                x0 = gap + i * (bar_w + gap)
                y0 = h / 2 - bh / 2
                c.create_rectangle(x0, y0, x0 + bar_w, y0 + bh, fill=base_color, outline="")
        except Exception:
            pass
        self.after(55, self._animate_voice_orb)

    # ════════════════════════════════════════
    #               SAAT
    # ════════════════════════════════════════

    def _tick(self):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        elapsed = int(time.time() - self.uptime_start)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        self.clock_lbl.configure(text=now)
        self.uptime_lbl.configure(text=f"⏱ {h:02d}:{m:02d}:{s:02d}  ·  {self.cmd_count} komut")
        self.after(1000, self._tick)

    # ════════════════════════════════════════
    #              PORT
    # ════════════════════════════════════════

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if ports:
            self.port_cb.configure(values=ports)
            self.port_cb.set("COM6" if "COM6" in ports else ports[0])
        else:
            self.port_cb.configure(values=["yok"])
            self.port_cb.set("yok")

    # ════════════════════════════════════════
    #             BAĞLANTI (THREAD'Lİ)
    # ════════════════════════════════════════

    def _toggle_conn(self):
        if self.connected:
            self._disconnect()
        else:
            self._start_connect()

    def _start_connect(self):
        port = self.port_cb.get()
        if port == "yok":
            self._log("❌ port bulunamadı")
            self._toast("port bulunamadı", "error")
            return
        self.conn_btn.configure(state="disabled", text="...")
        self.conn_dot.configure(text_color=C["orange"])
        self.conn_txt.configure(text="bağlanıyor...", text_color=C["orange"])
        threading.Thread(target=self._connect_worker, args=(port,), daemon=True).start()

    def _connect_worker(self, port):
        try:
            ser = serial.Serial(port, self.settings["baud"], timeout=0.1)
            time.sleep(2)
            self.ser = ser
            self.connected = True
            self.after(0, lambda: self._on_connected(port))
            threading.Thread(target=self._reader, daemon=True).start()
        except Exception as e:
            self.after(0, lambda: self._on_connect_failed(e))

    def _on_connected(self, port):
        self.conn_dot.configure(text_color=C["green"])
        self.conn_txt.configure(text="bağlandı", text_color=C["green"])
        self.conn_btn.configure(text="KES", fg_color=C["red"], hover_color="#e6334f", state="normal")
        self._log(f"✓ {port} bağlandı")
        self._toast(f"{port} bağlandı", "success")

    def _on_connect_failed(self, e):
        self.conn_dot.configure(text_color=C["red"])
        self.conn_txt.configure(text="bağlı değil", text_color=C["text2"])
        self.conn_btn.configure(text="BAĞLAN", fg_color=C["green"], hover_color="#00c278", state="normal")
        self._log(f"✗ bağlantı hatası: {e}")
        self._toast("bağlantı hatası", "error")

    def _disconnect(self):
        self.connected = False
        self.continuous_stop.set()
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None
        self.conn_dot.configure(text_color=C["red"])
        self.conn_txt.configure(text="bağlı değil", text_color=C["text2"])
        self.conn_btn.configure(text="BAĞLAN", fg_color=C["green"], hover_color="#00c278")
        self._log("bağlantı kesildi")
        self._toast("bağlantı kesildi", "info")

    # ════════════════════════════════════════
    #          SERİ PORT OKUYUCU
    # ════════════════════════════════════════

    def _reader(self):
        while self.connected and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting > 0:
                    line = self.ser.readline().decode(errors="ignore").strip()
                    if not line:
                        continue

                    if line.startswith("BUTTON:"):
                        st = line.split(":")[1]
                        self.relay = (st == "ON")
                        self.after(0, lambda s=st: self._log(f"buton → {'açık' if s == 'ON' else 'kapalı'}"))
                        self.after(0, lambda: self._orb_flash("success" if self.relay else "off"))
                        speak("Açıldı" if st == "ON" else "Kapandı")

                    elif line == "LONGPRESS":
                        self.after(0, lambda: self._log("🎤 arduino uzun basma → dinleme"))
                        self.after(0, lambda: self._orb_flash("voice"))
                        self.after(0, self._single_listen)

                    elif line.startswith("STATUS:"):
                        st = line.split(":")[1]
                        self.relay = (st == "ON")
                        self.after(0, lambda s=st: self._log(f"durum: {s}"))
                        self.after(0, lambda: self._orb_flash("info"))
                        speak(f"Röle {'açık' if st == 'ON' else 'kapalı'}")

                    elif line.startswith("OK:TOGGLE:"):
                        st = line.split(":")[2]
                        self.relay = (st == "ON")
                        self.after(0, lambda: self._orb_flash("success" if self.relay else "off"))

            except Exception:
                break
            time.sleep(0.03)

    # ════════════════════════════════════════
    #            KOMUT GÖNDERME
    # ════════════════════════════════════════

    def _cmd(self, cmd, src="gui"):
        if not self.connected or not self.ser:
            self._log("⚠ bağlantı yok")
            self._toast("bağlantı yok", "warning")
            self._orb_flash("error")
            speak("Bağlı değil")
            return
        try:
            self.ser.write((cmd + "\n").encode())
            time.sleep(0.12)
        except Exception as e:
            self._log(f"✗ gönderme hatası: {e}")
            self._toast("gönderme hatası", "error")
            self._orb_flash("error")
            return

        self.cmd_count += 1

        if cmd == "ON":
            self.relay = True
            self._log(f"⚡ aç [{src}]")
            self._orb_flash("success")
            speak("Açıldı")
        elif cmd == "OFF":
            self.relay = False
            self._log(f"● kapat [{src}]")
            self._orb_flash("off")
            speak("Kapandı")
        elif cmd == "TOGGLE":
            self.relay = not self.relay
            self._log(f"↻ toggle [{src}]")
            self._orb_flash("success" if self.relay else "off")
            speak("Değiştirildi")
        elif cmd == "STATUS":
            self._log(f"? durum [{src}]")
            self._orb_flash("info")

    # ════════════════════════════════════════
    #           YAZILI KOMUT
    # ════════════════════════════════════════

    def _text_cmd(self):
        txt = self.entry.get().strip()
        if not txt:
            return
        self.entry.delete(0, "end")
        self._log(f'» "{txt}"')

        intent, conf = extract_intent(txt)
        if intent:
            self.nlp_lbl.configure(text=f"→ {intent.lower()}  ·  güven %{conf}",
                                    text_color=C["green"] if conf >= 50 else C["orange"])
            self._cmd(intent, "nlp")
        else:
            self.nlp_lbl.configure(text="→ anlaşılamadı", text_color=C["red"])
            self._log("⚠ komut anlaşılamadı")
            self._toast("komut anlaşılamadı", "warning")
            speak("Anlayamadım")

    # ════════════════════════════════════════
    #        TEK SEFERLİK DİNLEME
    # ════════════════════════════════════════

    def _single_listen(self):
        if not HAS_SPEECH or self.listening:
            return
        self.listening = True
        self.voice_status.configure(text="dinleniyor...", text_color=C["green"])
        self.voice_result.configure(text="")
        threading.Thread(target=self._do_listen, args=(False,), daemon=True).start()

    def _do_listen(self, is_continuous):
        try:
            with self.mic as source:
                self.rec.adjust_for_ambient_noise(source, duration=0.4)
                self.after(0, lambda: self.voice_status.configure(text="🎤 konuşun...", text_color=C["green"]))
                audio = self.rec.listen(source, timeout=8, phrase_time_limit=10)

            self.after(0, lambda: self.voice_status.configure(text="işleniyor...", text_color=C["orange"]))

            text = self.rec.recognize_google(audio, language=self.settings["lang"])
            self.after(0, lambda: self.voice_result.configure(text=f'"{text}"', text_color=C["blue"]))
            self.after(0, lambda: self._log(f'🎤 "{text}"'))

            intent, conf = extract_intent(text)
            if intent:
                self.after(0, lambda: self.nlp_lbl.configure(
                    text=f"→ {intent.lower()}  ·  güven %{conf}", text_color=C["green"]))
                self.after(0, lambda: self._cmd(intent, "ses"))
            else:
                self.after(0, lambda: self._log("⚠ ses komutu anlaşılamadı"))
                self.after(0, lambda: self._toast("ses komutu anlaşılamadı", "warning"))
                speak("Anlayamadım")

        except sr.WaitTimeoutError:
            self.after(0, lambda: self._log("⏰ zaman aşımı"))
            self.after(0, lambda: self.voice_result.configure(text="zaman aşımı", text_color=C["text2"]))
        except sr.UnknownValueError:
            self.after(0, lambda: self._log("? ses anlaşılamadı"))
            self.after(0, lambda: self.voice_result.configure(text="anlaşılamadı", text_color=C["red"]))
            speak("Anlayamadım")
        except sr.RequestError as e:
            self.after(0, lambda: self._log(f"✗ internet: {e}"))
        except Exception as e:
            self.after(0, lambda: self._log(f"✗ hata: {e}"))
        finally:
            self.listening = False
            self.after(0, lambda: self.voice_status.configure(text="hazır", text_color=C["text2"]))

            if is_continuous and self.continuous_mode and not self.continuous_stop.is_set():
                time.sleep(0.5)
                self._do_listen(True)

    # ════════════════════════════════════════
    #          SÜREKLİ DİNLEME
    # ════════════════════════════════════════

    def _toggle_continuous(self):
        if self.continuous_mode:
            self._stop_continuous()
        else:
            self._start_continuous()

    def _start_continuous(self):
        if not HAS_SPEECH or not self.mic:
            return
        self.continuous_mode = True
        self.continuous_stop.clear()
        self.cont_btn.configure(fg_color=C["red"], text="■ DUR", text_color="#fff")
        self.voice_status.configure(text="sürekli dinleme aktif", text_color=C["green"])
        self._log("∞ sürekli dinleme başladı")
        self._toast("sürekli dinleme başladı", "info")
        speak("Sürekli dinleme başladı")
        threading.Thread(target=self._do_listen, args=(True,), daemon=True).start()

    def _stop_continuous(self):
        self.continuous_mode = False
        self.continuous_stop.set()
        self.cont_btn.configure(fg_color=C["surface"], text="∞ SÜREKLİ", text_color=C["text2"])
        self.voice_status.configure(text="hazır", text_color=C["text2"])
        self._log("∞ sürekli dinleme durdu")
        self._toast("sürekli dinleme durdu", "info")
        speak("Dinleme durdu")

    # ════════════════════════════════════════
    #            AYARLAR PANELİ
    # ════════════════════════════════════════

    def _open_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("Ayarlar")
        win.geometry("360x480")
        win.configure(fg_color=C["card"])
        win.attributes("-topmost", True)
        win.grab_set()

        ctk.CTkLabel(win, text="⚙ AYARLAR", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=C["text"]).pack(pady=(20, 16))

        ctk.CTkLabel(win, text="tanıma dili", font=ctk.CTkFont(size=11),
                     text_color=C["text2"]).pack(anchor="w", padx=24)
        lang_cb = ctk.CTkComboBox(win, values=["tr-TR", "en-US"], state="readonly",
                                   fg_color=C["surface"], button_color=C["surface"],
                                   dropdown_fg_color=C["card2"])
        lang_cb.set(self.settings["lang"])
        lang_cb.pack(fill="x", padx=24, pady=(4, 16))

        ctk.CTkLabel(win, text="baud rate", font=ctk.CTkFont(size=11),
                     text_color=C["text2"]).pack(anchor="w", padx=24)
        baud_cb = ctk.CTkComboBox(win, values=["9600", "19200", "38400", "57600", "115200"],
                                   state="readonly", fg_color=C["surface"], button_color=C["surface"],
                                   dropdown_fg_color=C["card2"])
        baud_cb.set(str(self.settings["baud"]))
        baud_cb.pack(fill="x", padx=24, pady=(4, 16))

        tts_var = tk.BooleanVar(value=self.settings["tts_enabled"])
        ctk.CTkSwitch(win, text="sesli geri bildirim", variable=tts_var,
                      progress_color=C["green"]).pack(anchor="w", padx=24, pady=(4, 16))

        ctk.CTkLabel(win, text="konuşma hızı", font=ctk.CTkFont(size=11),
                     text_color=C["text2"]).pack(anchor="w", padx=24)
        rate_slider = ctk.CTkSlider(win, from_=100, to=260, number_of_steps=32, progress_color=C["blue"])
        rate_slider.set(self.settings["tts_rate"])
        rate_slider.pack(fill="x", padx=24, pady=(4, 16))

        ctk.CTkButton(win, text="🔊 test et", fg_color=C["surface"], hover_color=C["border"],
                      command=lambda: speak("Bu bir test mesajıdır")).pack(pady=(0, 10))

        def _save():
            global TTS_ENABLED
            self.settings["lang"] = lang_cb.get()
            self.settings["baud"] = int(baud_cb.get())
            self.settings["tts_enabled"] = tts_var.get()
            self.settings["tts_rate"] = int(rate_slider.get())
            TTS_ENABLED = self.settings["tts_enabled"]
            if tts_engine:
                try:
                    tts_engine.setProperty("rate", self.settings["tts_rate"])
                except Exception:
                    pass
            self._log("⚙ ayarlar güncellendi")
            self._toast("ayarlar kaydedildi", "success")
            win.destroy()

        ctk.CTkButton(win, text="kaydet", fg_color=C["green"], text_color="#000",
                      hover_color="#00c278", command=_save).pack(pady=(10, 20), padx=24, fill="x")

    # ════════════════════════════════════════
    #          TOAST BİLDİRİMLERİ
    # ════════════════════════════════════════

    def _toast(self, message, kind="info"):
        color = {"info": C["blue"], "success": C["green"], "error": C["red"],
                 "warning": C["orange"]}.get(kind, C["blue"])
        icon = {"info": "ℹ", "success": "✓", "error": "✗", "warning": "⚠"}.get(kind, "ℹ")

        frame = ctk.CTkFrame(self, fg_color=C["card2"], corner_radius=10,
                              border_width=1, border_color=color)
        ctk.CTkLabel(frame, text=f"{icon}  {message}", font=ctk.CTkFont(size=12),
                     text_color=C["text"]).pack(padx=14, pady=9)

        y = 20 + len(self._toasts) * 50
        frame.place(relx=1.0, x=-20, y=y, anchor="ne")
        self._toasts.append(frame)
        self.after(3000, lambda: self._remove_toast(frame))

    def _remove_toast(self, frame):
        if frame in self._toasts:
            self._toasts.remove(frame)
        try:
            frame.destroy()
        except Exception:
            pass
        for i, f in enumerate(self._toasts):
            try:
                f.place_configure(y=20 + i * 50)
            except Exception:
                pass

    # ════════════════════════════════════════
    #               LOG
    # ════════════════════════════════════════

    def _log(self, msg):
        t = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f" {t}  {msg}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ════════════════════════════════════════
    #              KAPANIŞ
    # ════════════════════════════════════════

    def _quit(self):
        self._alive = False
        self.continuous_stop.set()
        self.continuous_mode = False
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(b"OFF\n")
                time.sleep(0.1)
                self.ser.close()
            except Exception:
                pass
        self.destroy()


# ═══════════════════════════════════
if __name__ == "__main__":
    App().mainloop()