import base64
import sys
import threading
import time
import traceback
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

try:
    from nudenet import NudeDetector
except Exception:
    NudeDetector = None


def resource_path(relative_path: str) -> str:
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    if (exe_dir / relative_path).is_file():
        return str(exe_dir / relative_path)
    base = Path(getattr(sys, '_MEIPASS', exe_dir))
    return str(base / relative_path)


class VisionDetector:
    # Vapes, cigarettes, smoke/vapor, and alcohol containers
    RESTRICTED_THRESHOLDS = {
        'vape': 0.12,
        'vape pen': 0.12,
        'vape mod': 0.12,
        'electronic cigarette': 0.12,
        'e-cigarette': 0.12,
        'cigarette': 0.22,
        'lighter': 0.26,
        'smoke': 0.18,
        'white smoke': 0.18,
        'vapor': 0.18,
        'cigarette smoke': 0.18,
        'beer bottle': 0.34,
        'liquor bottle': 0.33,
        'mini liquor bottle': 0.28,
        'shot glass': 0.30,
        'wine bottle': 0.45,
        'beer can': 0.35,
    }

    FAST_TRIGGER_LABELS = {
        'smoke',
        'white smoke',
        'vapor',
        'cigarette smoke',
    }

    # Explicit exposure labels from NudeNet (excludes benign face/belly/covered labels)
    EXPOSURE_THRESHOLDS = {
        'FEMALE_BREAST_EXPOSED': 0.45,
        'FEMALE_GENITALIA_EXPOSED': 0.40,
        'MALE_GENITALIA_EXPOSED': 0.40,
        'BUTTOCKS_EXPOSED': 0.45,
    }

    SAFE_DISTRACTORS = [
        'person',
        'microphone',
        'water bottle',
        'cup',
        'cell phone',
        'headphones',
        'pen',
    ]

    ALL_PROMPTS = list(RESTRICTED_THRESHOLDS.keys()) + SAFE_DISTRACTORS

    def __init__(self, risk_manager, camera_index=0, model_path='yoloe-11l-seg.pt', persist_seconds=0.6, fps=5.0):
        self.risk = risk_manager
        self.camera_index = int(camera_index)
        resolved = Path(model_path) if Path(model_path).is_file() else Path(resource_path('yoloe-11l-seg.pt'))
        self.model = YOLO(str(resolved))
        self._configure_open_vocab_prompts()
        self.nude_detector = self._init_nude_detector()
        self.nude_interval = 1.0
        self._last_nude_check = 0.0
        self.persist_seconds = min(float(persist_seconds), 0.7)
        self.interval = 1.0 / max(1.0, float(fps))
        self.stopping = threading.Event()
        self.first_seen = {}
        self.last_seen = {}
        self.clean_since = None
        self._last_debug_log = 0.0

    def _configure_open_vocab_prompts(self):
        """Registers precomputed open-vocabulary text embeddings on YOLOE (zero runtime downloads)."""
        try:
            cache_path = Path(resource_path('yoloe_text_pe.pt'))
            if cache_path.is_file():
                cached = torch.load(str(cache_path), map_location='cpu', weights_only=True)
                prompts = cached.get('prompts', self.ALL_PROMPTS)
                pe = cached['pe']
                self.model.set_classes(prompts, pe)
                return

            if hasattr(self.model, 'get_text_pe'):
                pe = self.model.get_text_pe(self.ALL_PROMPTS)
                self.model.set_classes(self.ALL_PROMPTS, pe)
                try:
                    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
                    torch.save({'prompts': self.ALL_PROMPTS, 'pe': pe}, str(exe_dir / 'yoloe_text_pe.pt'))
                except Exception:
                    pass
            elif hasattr(self.model, 'set_classes'):
                self.model.set_classes(self.ALL_PROMPTS)
        except Exception as exc:
            self.risk.emit(f'VISION: Text prompt setup warning ({exc})')

    def _init_nude_detector(self):
        if NudeDetector is None:
            self.risk.emit('VISION: NudeNet not installed — nudity guard skipped')
            return None
        try:
            return NudeDetector()
        except Exception as exc:
            self.risk.emit(f'VISION: NudeNet init failed ({exc}) — nudity guard skipped')
            return None

    def _scan_exposure(self, frame):
        if self.nude_detector is None:
            return {}
        try:
            preds = self.nude_detector.detect(frame)
        except Exception as exc:
            self.risk.emit(f'VISION [DEBUG]: NudeNet check error -> {exc}')
            return {}

        found = {}
        for item in preds or []:
            label = item.get('class') or item.get('label') or ''
            score = float(item.get('score', 0.0))
            min_conf = self.EXPOSURE_THRESHOLDS.get(label)
            if min_conf is not None and score >= min_conf:
                key = f'exposure:{label}'
                if score > found.get(key, 0.0):
                    found[key] = score
        return found

    def stop(self):
        self.stopping.set()
        self.risk.set_camera_censor(False)

    def _decode_obs_frame(self, b64_str):
        if not b64_str:
            return None
        if ',' in b64_str:
            b64_str = b64_str.split(',', 1)[1]
        raw = base64.b64decode(b64_str)
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def _open_local_camera(self):
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(self.camera_index)
        return cap if cap.isOpened() else None

    def run(self):
        cap = None
        use_obs = self.risk.obs_client is not None and bool(self.risk.cam_source)
        if use_obs:
            self.risk.emit(f'VISION: Monitoring OBS "{self.risk.cam_source}" (YOLOE + NudeNet)')
        else:
            cap = self._open_local_camera()
            if cap is None:
                self.risk.emit(f'VISION: Could not open local camera #{self.camera_index} (check Cam ID or OBS source)')
                return
            self.risk.emit(f'VISION: Monitoring local camera #{self.camera_index} (YOLOE + NudeNet)')

        empty_frames = 0
        safe_set = set(self.SAFE_DISTRACTORS)
        try:
            while not self.stopping.is_set():
                t0 = time.time()
                frame = None
                if use_obs:
                    frame = self._decode_obs_frame(self.risk.get_obs_frame_base64())
                elif cap is not None:
                    ok, frame = cap.read()
                    if not ok:
                        frame = None

                if frame is None:
                    empty_frames += 1
                    if empty_frames == 8 and use_obs:
                        self.risk.emit(f'VISION: No frames from OBS "{self.risk.cam_source}" — falling back to local camera #{self.camera_index}')
                        use_obs = False
                        cap = self._open_local_camera()
                        if cap is None:
                            self.risk.emit(f'VISION: Local camera #{self.camera_index} unavailable too — stopping Vision')
                            return
                        empty_frames = 0
                    time.sleep(0.2)
                    continue
                empty_frames = 0

                results = self.model.predict(frame, imgsz=640, conf=0.12, verbose=False)
                restricted_now = {}
                debug_all = {}

                for r in results:
                    names = r.names or {}
                    for box in r.boxes:
                        cid = int(box.cls[0])
                        score = float(box.conf[0])
                        label = names.get(cid, str(cid))

                        if label not in safe_set and score > debug_all.get(label, 0.0):
                            debug_all[label] = score

                        min_conf = self.RESTRICTED_THRESHOLDS.get(label)
                        if min_conf is not None and score >= min_conf:
                            if score > restricted_now.get(label, 0.0):
                                restricted_now[label] = score

                now = time.time()
                if now - self._last_nude_check >= self.nude_interval:
                    self._last_nude_check = now
                    exposure_hits = self._scan_exposure(frame)
                    for key, score in exposure_hits.items():
                        if score > restricted_now.get(key, 0.0):
                            restricted_now[key] = score
                        if score > debug_all.get(key, 0.0):
                            debug_all[key] = score

                if debug_all and now - self._last_debug_log >= 2.0:
                    summary = ', '.join(f'{k} ({v:.0%})' for k, v in debug_all.items())
                    self.risk.emit(f'VISION [DEBUG]: Candidates -> {summary}')
                    self._last_debug_log = now

                if restricted_now:
                    self.clean_since = None
                    for label, score in restricted_now.items():
                        self.last_seen[label] = now
                        start = self.first_seen.setdefault(label, now)
                        duration = now - start
                        is_exposure = label.startswith('exposure:')
                        req_duration = 0.4 if is_exposure else (0.2 if label in self.FAST_TRIGGER_LABELS else self.persist_seconds)
                        if duration >= req_duration:
                            category = 'VISION_EXPOSURE' if is_exposure else 'VISION_SUBSTANCE'
                            self.risk.trigger_event(
                                category=category,
                                detail=f'{label} detected ({score:.0%}, {duration:.1f}s)',
                                penalty=25.0 if is_exposure else 15.0,
                                cooldown_s=8.0,
                                obs_action='BLUR_WEBCAM',
                            )
                else:
                    for label in list(self.first_seen.keys()):
                        if now - self.last_seen.get(label, 0) > 1.0:
                            del self.first_seen[label]
                            self.last_seen.pop(label, None)

                    if not self.first_seen and self.risk.cam_censored:
                        if self.clean_since is None:
                            self.clean_since = now
                        elif now - self.clean_since >= 3.0:
                            self.risk.set_camera_censor(False)
                            self.clean_since = None

                elapsed = time.time() - t0
                if elapsed < self.interval:
                    time.sleep(self.interval - elapsed)
        except Exception as exc:
            self.risk.emit(f'VISION CRASH: {exc}')
            self.risk.emit(traceback.format_exc())
        finally:
            if cap is not None:
                cap.release()
            self.risk.set_camera_censor(False)
            self.risk.emit('VISION: Stopped')