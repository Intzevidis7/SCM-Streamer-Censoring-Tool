# ============================================================
#
#   I N T Z E V I D I S 7
#
#   Streamer Censoring Multitool (SCM) — AI Streamer Guard
#   Created by Intzevidis7
#   GitHub: https://github.com/Intzevidis7
#
#   © 2026 Intzevidis7. All rights reserved.
#   Unauthorized copying, modification, redistribution, or reuse of the
#   source code is prohibited.
#
#   "Every beep is a tiny piece of performance art."
#
# ============================================================
import json
import os
import queue
import re
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

import sounddevice as sd
from censor_engine import Censor

try:
    from risk_manager import RiskManager
except ImportError:
    RiskManager = None

try:
    from vision_detector import VisionDetector
except ImportError:
    VisionDetector = None

try:
    from music_detector import MusicCopyrightDetector
except ImportError:
    MusicCopyrightDetector = None

# Writable directory next to SCM.exe (for settings.json & logs)
ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
# Read-only bundled assets directory (_internal when frozen, project root when running from source)
BUNDLE_DIR = Path(getattr(sys, '_MEIPASS', ROOT))

MODELS = (ROOT / 'models') if (ROOT / 'models').exists() else (BUNDLE_DIR / 'models' if (BUNDLE_DIR / 'models').exists() else ROOT / 'models')
LOGS_DIR = ROOT / 'logs'
CONFIG = ROOT / 'settings.json'
GREEK_MODEL = MODELS / 'vosk-model-el-gr-0.7'
ENGLISH_MODEL = MODELS / 'vosk-model-small-en-us-0.15'
AUDIO_KEYWORD_MODEL = MODELS / 'keyword_v4'
YOLO_MODEL = (ROOT / 'yoloe-11l-seg.pt') if (ROOT / 'yoloe-11l-seg.pt').exists() else (BUNDLE_DIR / 'yoloe-11l-seg.pt')

THEMES = {
    'light': {
        'bg': '#f4f7fb',
        'card': '#ffffff',
        'border': '#d9e1ec',
        'text': '#172033',
        'muted': '#667085',
        'accent': '#635bff',
        'accent_active': '#5148e5',
        'accent_disabled': '#b7b4d9',
        'danger': '#b42318',
        'green': '#087443',
        'warn': '#b54708',
        'input_bg': '#ffffff',
        'popup_bg': '#ffffff',
        'popup_fg': '#172033',
        'log_bg': '#101828',
        'log_fg': '#d0d5dd',
        'switch_text': '🌙 Dark Mode',
    },
    'dark': {
        'bg': '#0f172a',
        'card': '#1e293b',
        'border': '#334155',
        'text': '#f8fafc',
        'muted': '#94a3b8',
        'accent': '#7c3aed',
        'accent_active': '#6d28d9',
        'accent_disabled': '#475569',
        'danger': '#f87171',
        'green': '#34d399',
        'warn': '#fbbf24',
        'input_bg': '#0f172a',
        'popup_bg': '#1e293b',
        'popup_fg': '#f8fafc',
        'log_bg': '#020617',
        'log_fg': '#e2e8f0',
        'switch_text': '☀️ Light Mode',
    },
}

MODES = {
    'Greek only — fastest for Greek streams': 'el',
    'English only — fastest for English streams': 'en',
    'Greek + English — mixed speech, higher CPU use': 'both',
}


class GUI:
    def __init__(self, root):
        self.root = root
        root.title('Streamer Censoring Multitool (SCM) — AI Streamer Guard')
        try:
            ico = BUNDLE_DIR / 'app.ico' if (BUNDLE_DIR / 'app.ico').exists() else ROOT / 'app.ico'
            root.iconbitmap(str(ico))
        except tk.TclError:
            pass
        root.geometry('1100x920')
        root.minsize(900, 740)

        self.events = queue.Queue()
        self.worker = self.censor = None
        self.risk_manager = None
        self.vision_detector = None
        self.music_detector = None

        self.inputs, self.outputs, self.saved = {}, {}, {}
        self.mic, self.output = tk.StringVar(), tk.StringVar()
        self.mode_label = tk.StringVar(value=list(MODES)[2])
        self.delay, self.volume = tk.StringVar(value='2'), tk.StringVar(value='0.04')
        self.fail_closed = tk.BooleanVar(value=False)
        self.audio_model = tk.BooleanVar(value=False)
        self.show_all_apis = tk.BooleanVar(value=False)

        # Theme state
        self.dark_mode = tk.BooleanVar(value=True)
        self.theme_btn_text = tk.StringVar(value=THEMES['dark']['switch_text'])

        # AI Streamer Multi-Tool variables
        self.vision_enabled = tk.BooleanVar(value=False)
        self.cam_index = tk.StringVar(value='0')
        self.vision_persist = tk.StringVar(value='2')

        self.music_enabled = tk.BooleanVar(value=False)
        self.loopback_device = tk.StringVar()
        self.audd_token = tk.StringVar(value='')

        self.obs_host = tk.StringVar(value='192.168.1.27')
        self.obs_port = tk.StringVar(value='4455')
        self.obs_password = tk.StringVar(value='')

        # Live telemetry variables
        self.current_score_val = 100.0
        self.has_active_alert = False
        self.safety_score = tk.StringVar(value='100.0 / 100')
        self.profanity_60s = tk.StringVar(value='0 / min')
        self.active_warning = tk.StringVar(value='No active policy alerts')
        self.status, self.status_detail = tk.StringVar(value='Stopped'), tk.StringVar(value='Ready to configure')

        self.load_settings()
        self.build_ui()
        self.apply_theme()
        self.refresh_devices()
        root.after(150, self.poll)
        root.after(10000, self.recovery_loop)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def _palette(self):
        return THEMES['dark' if self.dark_mode.get() else 'light']

    def toggle_theme(self):
        self.dark_mode.set(not self.dark_mode.get())
        self.apply_theme()
        self.save_settings()

    def apply_theme(self):
        p = self._palette()
        self.theme_btn_text.set(p['switch_text'])
        self.root.configure(bg=p['bg'])

        # Theme the native Combobox dropdown popup listboxes
        self.root.option_add('*TCombobox*Listbox*Background', p['popup_bg'])
        self.root.option_add('*TCombobox*Listbox*Foreground', p['popup_fg'])
        self.root.option_add('*TCombobox*Listbox*selectBackground', p['accent'])
        self.root.option_add('*TCombobox*Listbox*selectForeground', '#ffffff')
        self.root.option_add('*TCombobox*Listbox*Font', ('Segoe UI', 10))

        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        style.configure('.', font=('Segoe UI', 10), foreground=p['text'], background=p['card'])
        style.configure('App.TFrame', background=p['bg'])
        style.configure('Card.TFrame', background=p['card'])
        style.configure('Card.TLabelframe', background=p['card'], bordercolor=p['border'], lightcolor=p['border'], darkcolor=p['border'])
        style.configure('Card.TLabelframe.Label', background=p['card'], foreground=p['text'], font=('Segoe UI', 10, 'bold'))
        style.configure('Title.TLabel', background=p['bg'], foreground=p['text'], font=('Segoe UI', 24, 'bold'))
        style.configure('Subtitle.TLabel', background=p['bg'], foreground=p['muted'], font=('Segoe UI', 10))
        style.configure('SectionTitle.TLabel', background=p['bg'], foreground=p['text'], font=('Segoe UI', 11, 'bold'))
        style.configure('CardText.TLabel', background=p['card'], foreground=p['text'], font=('Segoe UI', 10))
        style.configure('Muted.TLabel', background=p['card'], foreground=p['muted'], font=('Segoe UI', 9))
        style.configure('ProfVal.TLabel', background=p['card'], foreground=p['text'], font=('Segoe UI', 14, 'bold'))
        style.configure('AuthorLink.TLabel', background=p['bg'], foreground=p['accent'], font=('Segoe UI', 9, 'underline'))
        style.configure('Primary.TButton', background=p['accent'], foreground='white', padding=(16, 9), font=('Segoe UI', 10, 'bold'), borderwidth=0)
        style.map('Primary.TButton', background=[('active', p['accent_active']), ('disabled', p['accent_disabled'])])
        style.configure('Secondary.TButton', background=p['card'], foreground=p['text'], bordercolor=p['border'], padding=(10, 6))
        style.map('Secondary.TButton', background=[('active', p['border'])])
        style.configure('TEntry', fieldbackground=p['input_bg'], foreground=p['text'], insertcolor=p['text'], bordercolor=p['border'], padding=6)
        style.configure('TCombobox', fieldbackground=p['input_bg'], background=p['card'], foreground=p['text'], arrowcolor=p['text'], bordercolor=p['border'], padding=6)
        style.map(
            'TCombobox',
            fieldbackground=[('readonly', p['input_bg'])],
            foreground=[('readonly', p['text'])],
            selectbackground=[('readonly', p['input_bg'])],
            selectforeground=[('readonly', p['text'])],
        )
        style.configure('TCheckbutton', background=p['card'], foreground=p['text'])
        style.map('TCheckbutton', background=[('active', p['card'])], foreground=[('active', p['text'])])

        self.status_lbl.configure(foreground=p['green'] if self.status.get() == 'Running' else p['text'])
        if self.current_score_val >= 80:
            self.score_lbl.configure(foreground=p['green'])
        elif self.current_score_val >= 50:
            self.score_lbl.configure(foreground=p['warn'])
        else:
            self.score_lbl.configure(foreground=p['danger'])

        self.alert_lbl.configure(foreground=p['danger'] if self.has_active_alert else p['muted'])
        self.log.configure(bg=p['log_bg'], fg=p['log_fg'], insertbackground=p['log_fg'])

    def build_ui(self):
        outer = ttk.Frame(self.root, padding=22, style='App.TFrame')
        outer.pack(fill='both', expand=True)

        # Header
        header = ttk.Frame(outer, style='App.TFrame')
        header.pack(fill='x', pady=(0, 12))
        left_head = ttk.Frame(header, style='App.TFrame')
        left_head.pack(side='left', fill='x', expand=True)
        ttk.Label(left_head, text='Streamer Censoring Multitool (SCM)', style='Title.TLabel').pack(anchor='w')
        ttk.Label(left_head, text='Pre-moderation multi-tool: speech censor, webcam substance & exposure guard, music monitor & OBS bridge', style='Subtitle.TLabel').pack(anchor='w', pady=(2, 0))
        github_label = ttk.Label(left_head, text='Created by Intzevidis7', style='AuthorLink.TLabel', cursor='hand2')
        github_label.pack(anchor='w', pady=(3, 0))
        github_label.bind('<Button-1>', lambda event: webbrowser.open_new('https://github.com/Intzevidis7'))

        right_head = ttk.Frame(header, style='App.TFrame')
        right_head.pack(side='right', anchor='ne')
        ttk.Button(right_head, textvariable=self.theme_btn_text, command=self.toggle_theme, style='Secondary.TButton').pack(side='left', padx=(0, 8))
        ttk.Button(right_head, text='Open Session Logs', command=self.open_logs, style='Secondary.TButton').pack(side='left', padx=(0, 8))
        ttk.Button(right_head, text='About / Credits', command=self.show_about, style='Secondary.TButton').pack(side='left')

        # Live Stream Safety Telemetry Card
        telemetry = ttk.LabelFrame(outer, text='  Live Stream Safety Score & Pre-Moderation Telemetry  ', padding=12, style='Card.TLabelframe')
        telemetry.pack(fill='x', pady=(0, 12))
        telemetry.columnconfigure(2, weight=1)

        score_box = ttk.Frame(telemetry, style='Card.TFrame')
        score_box.grid(row=0, column=0, sticky='w', padx=(0, 24))
        ttk.Label(score_box, text='STREAM SAFETY SCORE', style='Muted.TLabel').pack(anchor='w')
        self.score_lbl = ttk.Label(score_box, textvariable=self.safety_score, style='CardText.TLabel', font=('Segoe UI', 15, 'bold'))
        self.score_lbl.pack(anchor='w')

        prof_box = ttk.Frame(telemetry, style='Card.TFrame')
        prof_box.grid(row=0, column=1, sticky='w', padx=(0, 24))
        ttk.Label(prof_box, text='PROFANITY RATE (60s)', style='Muted.TLabel').pack(anchor='w')
        ttk.Label(prof_box, textvariable=self.profanity_60s, style='ProfVal.TLabel').pack(anchor='w')

        alert_box = ttk.Frame(telemetry, style='Card.TFrame')
        alert_box.grid(row=0, column=2, sticky='ew')
        ttk.Label(alert_box, text='LATEST PRE-MODERATION ALERT', style='Muted.TLabel').pack(anchor='w')
        self.alert_lbl = ttk.Label(alert_box, textvariable=self.active_warning, style='CardText.TLabel', font=('Segoe UI', 10, 'bold'))
        self.alert_lbl.pack(anchor='w', fill='x')

        # 1. Audio Routing
        route = ttk.LabelFrame(outer, text='  1  Audio routing  ', padding=12, style='Card.TLabelframe')
        route.pack(fill='x', pady=(0, 10))
        route.columnconfigure(1, weight=1)
        ttk.Label(route, text='Microphone', style='CardText.TLabel').grid(row=0, column=0, sticky='w', pady=4)
        self.mic_box = ttk.Combobox(route, textvariable=self.mic, state='readonly')
        self.mic_box.grid(row=0, column=1, sticky='ew', padx=14, pady=4)
        ttk.Label(route, text='Playback output', style='CardText.TLabel').grid(row=1, column=0, sticky='w', pady=4)
        self.out_box = ttk.Combobox(route, textvariable=self.output, state='readonly')
        self.out_box.grid(row=1, column=1, sticky='ew', padx=14, pady=4)

        route_controls = ttk.Frame(route, style='Card.TFrame')
        route_controls.grid(row=0, column=2, rowspan=2, padx=(6, 0), sticky='ns')
        ttk.Button(route_controls, text='Refresh devices', command=self.refresh_devices, style='Secondary.TButton').pack(fill='x', pady=(2, 4))
        ttk.Checkbutton(route_controls, text='Show all driver APIs', variable=self.show_all_apis, command=self.refresh_devices).pack(anchor='w')

        # 2. Recognition and Censor Settings
        settings = ttk.LabelFrame(outer, text='  2  Speech recognition & bleep settings  ', padding=12, style='Card.TLabelframe')
        settings.pack(fill='x', pady=(0, 10))
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text='Recognition mode', style='CardText.TLabel').grid(row=0, column=0, sticky='w', pady=4)
        self.mode_box = ttk.Combobox(settings, textvariable=self.mode_label, values=list(MODES), state='readonly')
        self.mode_box.grid(row=0, column=1, columnspan=5, sticky='ew', padx=(14, 0), pady=4)
        ttk.Label(settings, text='Delay (s)', style='CardText.TLabel').grid(row=1, column=0, sticky='w', pady=(8, 0))
        ttk.Entry(settings, textvariable=self.delay, width=8).grid(row=1, column=1, sticky='w', padx=(14, 6), pady=(8, 0))
        ttk.Label(settings, text='Beep volume', style='CardText.TLabel').grid(row=1, column=2, sticky='w', padx=(18, 0), pady=(8, 0))
        ttk.Entry(settings, textvariable=self.volume, width=8).grid(row=1, column=3, sticky='w', padx=(8, 6), pady=(8, 0))
        ttk.Checkbutton(settings, text='Mute unanalyzed audio', variable=self.fail_closed).grid(row=1, column=4, sticky='w', padx=(18, 0), pady=(8, 0))
        ttk.Checkbutton(settings, text='AI audio keyword model', variable=self.audio_model).grid(row=1, column=5, sticky='w', padx=(14, 0), pady=(8, 0))

        # 3. AI Multi-Tool Modules (Vision, Music Copyright, OBS)
        multitool = ttk.LabelFrame(outer, text='  3  AI Vision, DMCA Music Guard & OBS WebSocket  ', padding=12, style='Card.TLabelframe')
        multitool.pack(fill='x', pady=(0, 10))
        multitool.columnconfigure(1, weight=1)

        # Row 0: Vision
        vis_row = ttk.Frame(multitool, style='Card.TFrame')
        vis_row.grid(row=0, column=0, columnspan=2, sticky='ew', pady=4)
        ttk.Checkbutton(vis_row, text='Enable Webcam Vision Guard', variable=self.vision_enabled).pack(side='left')
        ttk.Label(vis_row, text='Cam ID:', style='CardText.TLabel').pack(side='left', padx=(24, 6))
        ttk.Entry(vis_row, textvariable=self.cam_index, width=5).pack(side='left')
        ttk.Label(vis_row, text='Alert after (sec):', style='CardText.TLabel').pack(side='left', padx=(24, 6))
        ttk.Entry(vis_row, textvariable=self.vision_persist, width=6).pack(side='left')

        # Row 1: Music Copyright
        mus_top = ttk.Frame(multitool, style='Card.TFrame')
        mus_top.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(6, 2))
        ttk.Checkbutton(mus_top, text='Enable Music Copyright Guard', variable=self.music_enabled).pack(side='left')
        ttk.Label(mus_top, text='AudD API Token:', style='CardText.TLabel').pack(side='left', padx=(24, 6))
        audd_entry = ttk.Entry(mus_top, textvariable=self.audd_token, width=32, show='*')
        audd_entry.pack(side='left')
        audd_entry.bind('<FocusOut>', lambda e: self.save_settings())

        ttk.Label(multitool, text='Desktop Audio Output', style='CardText.TLabel').grid(row=2, column=0, sticky='w', pady=4)
        self.loopback_box = ttk.Combobox(multitool, textvariable=self.loopback_device, state='readonly')
        self.loopback_box.grid(row=2, column=1, sticky='ew', padx=(14, 0), pady=4)

        # Row 3: OBS WebSocket
        ttk.Label(multitool, text='OBS WebSocket', style='CardText.TLabel').grid(row=3, column=0, sticky='w', pady=(6, 0))
        obs_frame = ttk.Frame(multitool, style='Card.TFrame')
        obs_frame.grid(row=3, column=1, sticky='w', padx=(14, 0), pady=(6, 0))
        ttk.Label(obs_frame, text='Host:', style='Muted.TLabel').pack(side='left', padx=(0, 4))
        obs_host_entry = ttk.Entry(obs_frame, textvariable=self.obs_host, width=14)
        obs_host_entry.pack(side='left', padx=(0, 12))
        obs_host_entry.bind('<FocusOut>', lambda e: self.save_settings())
        ttk.Label(obs_frame, text='Port:', style='Muted.TLabel').pack(side='left', padx=(0, 4))
        obs_port_entry = ttk.Entry(obs_frame, textvariable=self.obs_port, width=7)
        obs_port_entry.pack(side='left', padx=(0, 12))
        obs_port_entry.bind('<FocusOut>', lambda e: self.save_settings())
        ttk.Label(obs_frame, text='Password:', style='Muted.TLabel').pack(side='left', padx=(0, 4))
        obs_pass_entry = ttk.Entry(obs_frame, textvariable=self.obs_password, width=20, show='*')
        obs_pass_entry.pack(side='left')
        obs_pass_entry.bind('<FocusOut>', lambda e: self.save_settings())

        # Actions
        actions = ttk.Frame(outer, style='App.TFrame')
        actions.pack(fill='x', pady=(4, 10))
        self.start_btn = ttk.Button(actions, text='Start Streamer Guard', command=self.start, style='Primary.TButton')
        self.start_btn.pack(side='left')
        self.stop_btn = ttk.Button(actions, text='Stop', command=self.stop, state='disabled', style='Secondary.TButton')
        self.stop_btn.pack(side='left', padx=10)
        ttk.Button(actions, text='Open active word list', command=self.open_words, style='Secondary.TButton').pack(side='left')
        ttk.Button(actions, text='Save settings', command=self.save_settings_manual, style='Secondary.TButton').pack(side='left', padx=(10, 0))
        status = ttk.Frame(actions, style='App.TFrame')
        status.pack(side='right')
        self.status_lbl = ttk.Label(status, textvariable=self.status, style='Title.TLabel', font=('Segoe UI', 11, 'bold'))
        self.status_lbl.pack(anchor='e')
        ttk.Label(status, textvariable=self.status_detail, style='Subtitle.TLabel').pack(anchor='e')

        # Log
        h = ttk.Frame(outer, style='App.TFrame')
        h.pack(fill='x')
        ttk.Label(h, text='Activity & Pre-Moderation Log', style='SectionTitle.TLabel').pack(side='left')
        ttk.Label(h, text='  BEEP  •  VISION  •  MUSIC  •  OBS  •  lag', style='Subtitle.TLabel').pack(side='left')
        self.log = scrolledtext.ScrolledText(outer, state='disabled', wrap='word', height=10, relief='flat', borderwidth=0, padx=12, pady=10, font=('Consolas', 9))
        self.log.pack(fill='both', expand=True, pady=(6, 0))

    def show_about(self):
        messagebox.showinfo(
            'About / Credits — Streamer Censoring Multitool (SCM)',
            'Streamer Censoring Multitool (SCM) — AI Streamer Guard\n'
            'Created by Intzevidis7\n'
            '© 2026 Intzevidis7. All rights reserved.\n\n'
            'GitHub: https://github.com/Intzevidis7\n\n'
            'Third-party acknowledgments\n'
            'Vosk — Alpha Cephei\n'
            'Ultralytics YOLOE / NudeNet / OpenCV\n'
            'OBS WebSocket (obsws-python)\n'
            'python-sounddevice, pyaudiowpatch, and PortAudio',
            parent=self.root,
        )

    def active_lists(self):
        mode = MODES[self.mode_label.get()]
        if mode == 'el':
            return [BUNDLE_DIR / 'bad_words_el.txt', BUNDLE_DIR / 'bad_words_greeklish.txt']
        if mode == 'en':
            return [BUNDLE_DIR / 'bad_words_en.txt']
        return [BUNDLE_DIR / 'bad_words_el.txt', BUNDLE_DIR / 'bad_words_en.txt', BUNDLE_DIR / 'bad_words_greeklish.txt']

    def append(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', str(text).rstrip() + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 1500:
            self.log.delete('1.0', '301.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def save_settings_manual(self):
        self.save_settings()
        self.append('Settings & credentials saved to settings.json')

    def save_settings(self):
        try:
            data = json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {}
        except (OSError, ValueError):
            data = {}
        data.update(
            {
                'dark_mode': self.dark_mode.get(),
                'show_all_apis': self.show_all_apis.get(),
                'mic': self.mic.get(),
                'output': self.output.get(),
                'loopback_device': self.loopback_device.get(),
                'delay': self.delay.get(),
                'volume': self.volume.get(),
                'mode_label': self.mode_label.get(),
                'fail_closed': self.fail_closed.get(),
                'audio_model': self.audio_model.get(),
                'vision_enabled': self.vision_enabled.get(),
                'cam_index': self.cam_index.get(),
                'vision_persist': self.vision_persist.get(),
                'music_enabled': self.music_enabled.get(),
                'audd_token': self.audd_token.get(),
                'obs_host': self.obs_host.get(),
                'obs_port': self.obs_port.get(),
                'obs_password': self.obs_password.get(),
            }
        )
        try:
            CONFIG.write_text(json.dumps(data, indent=2), encoding='utf-8')
        except OSError as exc:
            if hasattr(self, 'log'):
                self.append(f'Could not save settings: {exc}')

    def load_settings(self):
        try:
            self.saved = json.loads(CONFIG.read_text(encoding='utf-8'))
            self.dark_mode.set(bool(self.saved.get('dark_mode', True)))
            self.show_all_apis.set(bool(self.saved.get('show_all_apis', False)))
            for name, var in (
                ('delay', self.delay),
                ('volume', self.volume),
                ('mode_label', self.mode_label),
                ('cam_index', self.cam_index),
                ('vision_persist', self.vision_persist),
                ('audd_token', self.audd_token),
                ('obs_host', self.obs_host),
                ('obs_port', self.obs_port),
                ('obs_password', self.obs_password),
            ):
                if name in self.saved:
                    var.set(str(self.saved[name]))
            if self.mode_label.get() not in MODES:
                self.mode_label.set(list(MODES)[2])
            self.fail_closed.set(bool(self.saved.get('fail_closed', False)))
            self.audio_model.set(bool(self.saved.get('audio_model', False)))
            self.vision_enabled.set(bool(self.saved.get('vision_enabled', False)))
            self.music_enabled.set(bool(self.saved.get('music_enabled', False)))
        except (OSError, ValueError):
            pass

    def refresh_devices(self):
        old_mic = self.mic.get() or self.saved.get('mic', '')
        old_out = self.output.get() or self.saved.get('output', '')
        old_loop = self.loopback_device.get() or self.saved.get('loopback_device', '')
        try:
            devices, apis = sd.query_devices(), sd.query_hostapis()
        except Exception as exc:
            messagebox.showerror('Audio devices', str(exc))
            return

        preferred_apis = {'Windows DirectSound', 'Windows WASAPI'}
        show_all = self.show_all_apis.get()

        self.inputs, self.outputs = {}, {}
        for i, d in enumerate(devices):
            api_name = apis[d['hostapi']]['name']
            if not show_all and sys.platform == 'win32' and api_name not in preferred_apis:
                continue
            short_api = api_name.replace('Windows ', '')
            khz = f"{d['default_samplerate'] / 1000:.1f} kHz".replace('.0 kHz', ' kHz')
            label = f"#{i:02d}  {d['name']}  ({short_api} • {khz})"
            if d['max_input_channels']:
                self.inputs[label] = i
            if d['max_output_channels']:
                self.outputs[label] = i

        self.mic_box['values'] = list(self.inputs)
        self.out_box['values'] = list(self.outputs)
        self.loopback_box['values'] = list(self.outputs)

        def _match_saved(saved_str, mapping):
            if saved_str in mapping:
                return saved_str
            m = re.match(r'^#?(\d+)\b', str(saved_str).strip())
            if m:
                dev_id = int(m.group(1))
                for k, v in mapping.items():
                    if v == dev_id:
                        return k
            return None

        self.mic.set(_match_saved(old_mic, self.inputs) or next(iter(self.inputs), ''))
        cable = next((v for v in self.outputs if re.search(r'\bCABLE Input\b', v, re.I)), '')
        self.output.set(_match_saved(old_out, self.outputs) or cable or next(iter(self.outputs), ''))

        default_spk = next((v for v in self.outputs if not re.search(r'\bCABLE Input\b', v, re.I)), '')
        self.loopback_device.set(_match_saved(old_loop, self.outputs) or default_spk or next(iter(self.outputs), ''))

    def _emit_event(self, payload):
        if isinstance(payload, tuple):
            self.events.put(payload)
        else:
            self.events.put(('log', str(payload)))

    def _launch_model_downloader(self):
        models_exe = ROOT / 'SCM-Models.exe'
        if models_exe.is_file():
            subprocess.Popen([str(models_exe)], cwd=str(ROOT))
        else:
            script = BUNDLE_DIR / 'models_setup.py' if (BUNDLE_DIR / 'models_setup.py').exists() else ROOT / 'models_setup.py'
            subprocess.Popen([sys.executable, str(script)], cwd=str(ROOT))

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.save_settings()
        mode = MODES[self.mode_label.get()]
        needed = []
        if mode in ('el', 'both'):
            needed.append(('Greek', GREEK_MODEL))
        if mode in ('en', 'both'):
            needed.append(('English', ENGLISH_MODEL))
        for name, path in needed:
            if not (path / 'am' / 'final.mdl').is_file():
                if messagebox.askyesno(
                    f'{name} model missing',
                    f'Expected model at:\n{path}\n\nDownload the Vosk speech models now?',
                ):
                    self._launch_model_downloader()
                return
        lists = self.active_lists()
        missing = [p.name for p in lists if not p.is_file()]
        if missing:
            messagebox.showerror('Word list missing', 'Missing:\n' + '\n'.join(missing))
            return
        if self.audio_model.get() and not (AUDIO_KEYWORD_MODEL / 'model.pt').is_file():
            messagebox.showerror('AI audio model missing', f'Expected model at:\n{AUDIO_KEYWORD_MODEL / "model.pt"}')
            return
        try:
            inp, out = self.inputs[self.mic.get()], self.outputs[self.output.get()]
            delay, volume = float(self.delay.get()), float(self.volume.get())
            if not (2 <= delay <= 120 and 0 <= volume <= .3):
                raise ValueError('Delay must be 2–120 seconds, beep volume 0–0.3')
            rate = round(sd.query_devices(inp)['default_samplerate'])
            if rate != round(sd.query_devices(out)['default_samplerate']):
                raise ValueError('Devices have different default sample rates; choose another entry')
            sd.check_input_settings(device=inp, channels=1, samplerate=rate)
            sd.check_output_settings(device=out, channels=1, samplerate=rate)
        except Exception as exc:
            messagebox.showerror('Check settings', str(exc))
            return
        if 'cable input' not in self.output.get().lower() and not messagebox.askyesno('Check cable', 'You did not choose CABLE Input. Continue?'):
            return

        self.save_settings()
        p = self._palette()

        self.current_score_val = 100.0
        self.has_active_alert = False
        self.safety_score.set('100.0 / 100')
        self.score_lbl.configure(foreground=p['green'])
        self.profanity_60s.set('0 / min')
        self.active_warning.set('Monitoring stream...')
        self.alert_lbl.configure(foreground=p['muted'])

        self.start_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        self.status.set('Starting…')
        self.status_detail.set(f'Loading {self.mode_label.get().split(" — ")[0]} model(s)')

        if RiskManager is not None:
            try:
                obs_port_int = int(self.obs_port.get() or 4455)
            except ValueError:
                obs_port_int = 4455
            self.risk_manager = RiskManager(
                log_dir=LOGS_DIR,
                emit_fn=self._emit_event,
                obs_host=self.obs_host.get().strip() or '192.168.1.27',
                obs_port=obs_port_int,
                obs_password=self.obs_password.get(),
            )
        else:
            self.risk_manager = None

        if self.vision_enabled.get() and self.risk_manager and VisionDetector is not None:
            try:
                model_file = str(YOLO_MODEL) if YOLO_MODEL.is_file() else 'yoloe-11l-seg.pt'
                self.vision_detector = VisionDetector(
                    risk_manager=self.risk_manager,
                    camera_index=int(self.cam_index.get() or 0),
                    model_path=model_file,
                    persist_seconds=float(self.vision_persist.get() or 2.0),
                )
                threading.Thread(target=self.vision_detector.run, daemon=True).start()
            except Exception as exc:
                self.append(f'VISION init error: {exc}')

        if self.music_enabled.get() and self.risk_manager and MusicCopyrightDetector is not None:
            try:
                loop_name = self.loopback_device.get()
                loop_id = self.outputs.get(loop_name, out)
                whitelist_file = BUNDLE_DIR / 'music_whitelist.txt' if (BUNDLE_DIR / 'music_whitelist.txt').exists() else ROOT / 'music_whitelist.txt'
                self.music_detector = MusicCopyrightDetector(
                    risk_manager=self.risk_manager,
                    loopback_device_id=loop_id,
                    loopback_device_name=loop_name,
                    api_token=self.audd_token.get(),
                    whitelist_path=whitelist_file,
                )
                threading.Thread(target=self.music_detector.run, daemon=True).start()
            except Exception as exc:
                self.append(f'MUSIC init error: {exc}')

        def run():
            try:
                self.censor = Censor(
                    inp,
                    out,
                    delay,
                    volume,
                    mode,
                    GREEK_MODEL,
                    ENGLISH_MODEL,
                    lists,
                    fail_closed=self.fail_closed.get(),
                    events=self._emit_event,
                    audio_model=self.audio_model.get(),
                    audio_model_dir=AUDIO_KEYWORD_MODEL,
                    audio_threshold=0.65,
                    on_profanity=self.risk_manager.record_profanity if self.risk_manager else None,
                )
                self.censor.run()
            except Exception as exc:
                self.events.put(('log', f'ERROR: {exc}'))
            finally:
                self.events.put(('done', None))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def recovery_loop(self):
        if self.risk_manager and self.worker and self.worker.is_alive():
            self.risk_manager.recover_tick(amount=0.5)
        self.root.after(10000, self.recovery_loop)

    def poll(self):
        p = self._palette()
        try:
            while True:
                item = self.events.get_nowait()
                kind = item[0]
                if kind == 'log':
                    text = item[1]
                    self.append(text)
                    if str(text).startswith('Running:'):
                        self.status.set('Running')
                        self.status_lbl.configure(foreground=p['green'])
                        self.status_detail.set('Multi-tool guard active')
                elif kind == 'alert':
                    msg = item[1]
                    self.has_active_alert = True
                    self.active_warning.set(msg)
                    self.alert_lbl.configure(foreground=p['danger'])
                    self.append(f'ALERT >> {msg}')
                elif kind == 'metric':
                    metric_name, val = item[1], item[2]
                    if metric_name == 'safety_score':
                        self.current_score_val = float(val)
                        self.safety_score.set(f'{val:.1f} / 100')
                        if val >= 80:
                            self.score_lbl.configure(foreground=p['green'])
                        elif val >= 50:
                            self.score_lbl.configure(foreground=p['warn'])
                        else:
                            self.score_lbl.configure(foreground=p['danger'])
                    elif metric_name == 'profanity_60s':
                        self.profanity_60s.set(f'{val} / min')
                elif kind == 'done':
                    self.censor = self.worker = None
                    if self.vision_detector:
                        self.vision_detector.stop()
                        self.vision_detector = None
                    if self.music_detector:
                        self.music_detector.stop()
                        self.music_detector = None
                    self.risk_manager = None
                    self.status.set('Stopped')
                    self.status_lbl.configure(foreground=p['text'])
                    self.status_detail.set('Ready to configure')
                    self.start_btn.configure(state='normal')
                    self.stop_btn.configure(state='disabled')
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def stop(self):
        if self.censor:
            self.censor.stop()
        if self.vision_detector:
            self.vision_detector.stop()
        if self.music_detector:
            self.music_detector.stop()
        self.status.set('Stopping…')
        self.status_detail.set('Releasing audio & vision devices')

    def open_words(self):
        files = self.active_lists()
        if sys.platform == 'win32':
            for path in files:
                if path.exists():
                    os.startfile(str(path))
        else:
            messagebox.showinfo('Active word lists', '\n'.join(map(str, files)))

    def open_logs(self):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(str(LOGS_DIR))
        else:
            messagebox.showinfo('Logs folder', str(LOGS_DIR))

    def close(self):
        self.save_settings()
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno('Stop guard?', 'Closing this window stops the Streamer Guard. Close?'):
                return
            self.stop()
            self.worker.join(timeout=5)
            if self.worker.is_alive():
                messagebox.showwarning('Still stopping', 'Wait for the audio device to release, then close again.')
                return
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    GUI(root)
    root.mainloop()