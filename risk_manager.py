import csv
import ctypes
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

try:
    import obsws_python as obs
except ImportError:
    obs = None


def pause_system_media():
    """Sends hardware Media Play/Pause key on Windows to pause Spotify/YouTube/players."""
    try:
        VK_MEDIA_PLAY_PAUSE = 0xB3
        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_EXTENDEDKEY, 0)
        ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


class RiskManager:
    def __init__(
        self,
        log_dir,
        emit_fn,
        obs_host='localhost',
        obs_port=4455,
        obs_password='',
        cam_source='Webcam',
        blur_filter='Blur',
        music_source='Desktop Audio',
    ):
        self.emit = emit_fn
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.obs_lock = threading.Lock()

        self.cam_source = cam_source
        self.blur_filter = blur_filter
        self.music_source = music_source

        self.score = 100.0
        self.session_start = time.time()
        self.swear_timestamps = deque()
        self.cooldowns = {}
        self.cam_censored = False

        session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.csv_path = self.log_dir / f'session_{session_id}.csv'
        with self.csv_path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['stream_time', 'category', 'detail', 'penalty', 'new_score', 'action_taken'])

        self.obs_client = None
        if obs is not None:
            try:
                self.obs_client = obs.ReqClient(host=obs_host, port=obs_port, password=obs_password, timeout=3)
                self.emit(f'OBS: Connected ({obs_host}:{obs_port})')
                self._ensure_obs_censor_ready()
            except Exception as exc:
                self.emit(f'OBS: Not connected ({exc})')

    def _ensure_obs_censor_ready(self):
        """Auto-creates a built-in Color Correction blackout/blur filter if missing so no plugin is required."""
        if not self.obs_client:
            return
        with self.obs_lock:
            try:
                filters = self.obs_client.get_source_filter_list(self.cam_source).filters
                names = [f['filterName'] for f in filters]
                if self.blur_filter not in names:
                    self.obs_client.create_source_filter(
                        source_name=self.cam_source,
                        filter_name=self.blur_filter,
                        filter_kind='color_filter_v2',
                        filter_settings={'opacity': 0.05, 'contrast': -2.0, 'brightness': -0.8},
                    )
                    self.obs_client.set_source_filter_enabled(self.cam_source, self.blur_filter, False)
                    self.emit(f'OBS: Auto-created "{self.blur_filter}" filter on "{self.cam_source}"')
            except Exception as exc:
                self.emit(f'OBS: Filter check skipped ({exc})')

    def get_obs_frame_base64(self):
            """Grabs a live 640x360 frame directly from OBS so small objects like vapes are sharp enough to detect."""
            if not self.obs_client:
                return None
            with self.obs_lock:
                try:
                    resp = self.obs_client.get_source_screenshot(
                        name=self.cam_source,
                        img_format='jpg',
                        width=640,
                        height=360,
                        quality=80,
                    )
                    return resp.image_data
                except Exception:
                    return None

    def set_camera_censor(self, enabled: bool):
        if not self.obs_client or self.cam_censored == enabled:
            return
        with self.obs_lock:
            try:
                self.obs_client.set_source_filter_enabled(self.cam_source, self.blur_filter, enabled)
                self.cam_censored = enabled
                self.emit(f'OBS: {"Blurred/hid" if enabled else "Restored"} "{self.cam_source}"')
            except Exception as exc:
                self.emit(f'OBS: Camera censor failed ({exc})')

    def _stream_timestamp(self):
        elapsed = int(time.time() - self.session_start)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        return f'{h:02d}:{m:02d}:{s:02d}'

    def record_profanity(self, lang, word, threshold_per_min=5):
        now = time.time()
        with self.lock:
            self.swear_timestamps.append(now)
            while self.swear_timestamps and now - self.swear_timestamps[0] > 60.0:
                self.swear_timestamps.popleft()
            count_60s = len(self.swear_timestamps)

        self.emit(('metric', 'profanity_60s', count_60s))
        if count_60s >= threshold_per_min:
            self.trigger_event(
                category='SPEECH_HIGH_DENSITY',
                detail=f'{count_60s} profanities in 60s (last: {word} [{lang}])',
                penalty=5.0,
                cooldown_s=20.0,
                obs_action='WARN_SPEECH',
            )

    def trigger_event(self, category, detail, penalty, cooldown_s=15.0, obs_action=None):
        now = time.time()
        with self.lock:
            if now - self.cooldowns.get(category, 0) < cooldown_s:
                return
            self.cooldowns[category] = now
            self.score = max(0.0, round(self.score - penalty, 1))
            current_score = self.score

        ts = self._stream_timestamp()
        action_taken = self._execute_obs_action(obs_action)

        with self.csv_path.open('a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow([ts, category, detail, -penalty, current_score, action_taken])

        self.emit(('alert', f'[{ts}] {category}: {detail} | Action: {action_taken}'))
        self.emit(('metric', 'safety_score', current_score))

    def recover_tick(self, amount=0.5):
        with self.lock:
            if self.score < 100.0:
                self.score = min(100.0, round(self.score + amount, 1))
                self.emit(('metric', 'safety_score', self.score))

    def _execute_obs_action(self, action):
        actions = []
        if action == 'STOP_MUSIC':
            if pause_system_media():
                actions.append('PAUSED_MEDIA_PLAYER')
            if self.obs_client:
                with self.obs_lock:
                    try:
                        self.obs_client.set_input_mute(self.music_source, True)
                        actions.append(f'OBS_MUTED_{self.music_source}')
                    except Exception as exc:
                        actions.append(f'OBS_MUTE_ERR({exc})')
        elif action == 'BLUR_WEBCAM':
            self.set_camera_censor(True)
            if self.cam_censored:
                actions.append(f'OBS_BLURRED_{self.cam_source}')
        return '+'.join(actions) if actions else 'UI_WARNING_ONLY'