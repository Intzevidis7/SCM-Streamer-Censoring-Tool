import io
import re
import threading
import time
import wave
from pathlib import Path

import numpy as np
import requests
import sounddevice as sd

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    pyaudio = None


class MusicCopyrightDetector:
    def __init__(self, risk_manager, loopback_device_id, api_token, whitelist_path='music_whitelist.txt', check_interval=8.0, loopback_device_name=''):
        self.risk = risk_manager
        self.device_id = int(loopback_device_id)
        clean = re.sub(r'^#\d+\s+', '', str(loopback_device_name))
        self.device_name = re.sub(r'\s+\([^)]+•[^)]+\)$', '', clean).strip()
        self.api_token = api_token.strip()
        self.check_interval = float(check_interval)
        self.stopping = threading.Event()
        self.whitelist = self._load_whitelist(whitelist_path)

    def _load_whitelist(self, path):
        p = Path(path)
        if not p.exists():
            return set()
        return {line.strip().casefold() for line in p.read_text(encoding='utf-8').splitlines() if line.strip() and not line.startswith('#')}

    def stop(self):
        self.stopping.set()

    def _record_wasapi_loopback(self, seconds=7.0):
        if pyaudio is None:
            return None
        p = pyaudio.PyAudio()
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            target_loopback = None

            if self.device_name:
                for loopback in p.get_loopback_device_info_generator():
                    if self.device_name.lower() in loopback['name'].lower():
                        target_loopback = loopback
                        break

            if target_loopback is None:
                default_speakers = p.get_device_info_by_index(wasapi_info['defaultOutputDevice'])
                if default_speakers.get('isLoopbackDevice', False):
                    target_loopback = default_speakers
                else:
                    for loopback in p.get_loopback_device_info_generator():
                        if default_speakers['name'] in loopback['name']:
                            target_loopback = loopback
                            break

            if target_loopback is None:
                return None

            rate = int(target_loopback['defaultSampleRate'])
            channels = int(target_loopback['maxInputChannels'])
            chunk = 1024
            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=target_loopback['index'],
                frames_per_buffer=chunk,
            )
            frames = []
            for _ in range(int(rate / chunk * seconds)):
                if self.stopping.is_set():
                    break
                frames.append(stream.read(chunk, exception_on_overflow=False))
            stream.stop_stream()
            stream.close()

            raw = np.frombuffer(b''.join(frames), dtype=np.int16)
            if channels > 1:
                raw = raw.reshape(-1, channels).mean(axis=1).astype(np.int16)
            if np.abs(raw).mean() < 18:
                return None

            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                wf.writeframes(raw.tobytes())
            return buf.getvalue()
        finally:
            p.terminate()

    def _record_fallback_input(self, seconds=7.0, rate=44100):
        frames = int(seconds * rate)
        audio = sd.rec(frames, samplerate=rate, channels=1, dtype='int16', device=self.device_id)
        sd.wait()
        if np.abs(audio).mean() < 18:
            return None
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(audio.tobytes())
        return buf.getvalue()

    def run(self):
        if not self.api_token:
            self.risk.emit('MUSIC: Disabled (enter AudD API token first)')
            return
        target_label = self.device_name or f'Device #{self.device_id}'
        mode = f'WASAPI Loopback ({target_label})' if pyaudio is not None else f'Input device #{self.device_id}'
        self.risk.emit(f'MUSIC: Monitoring desktop audio via {mode}')

        while not self.stopping.is_set():
            try:
                wav_bytes = self._record_wasapi_loopback(seconds=7.0) if pyaudio is not None else self._record_fallback_input(seconds=7.0)
                if wav_bytes:
                    resp = requests.post(
                        'https://api.audd.io/',
                        data={'api_token': self.api_token},
                        files={'file': ('clip.wav', wav_bytes, 'audio/wav')},
                        timeout=10,
                    ).json()
                    if resp.get('status') == 'error':
                        err = resp.get('error', {}).get('error_message', 'AudD API error')
                        self.risk.emit(f'MUSIC: {err}')
                    result = resp.get('result')
                    if result:
                        artist = result.get('artist', 'Unknown')
                        title = result.get('title', 'Unknown')
                        track_key = f'{artist} - {title}'.casefold()
                        if track_key not in self.whitelist:
                            self.risk.trigger_event(
                                category='MUSIC_COPYRIGHT',
                                detail=f'Copyrighted track: {artist} - {title}',
                                penalty=25.0,
                                cooldown_s=15.0,
                                obs_action='STOP_MUSIC',
                            )
                        else:
                            self.risk.emit(f'MUSIC: Whitelisted track ({artist} - {title})')
            except Exception as exc:
                self.risk.emit(f'MUSIC: Check error ({exc})')
            self.stopping.wait(self.check_interval)
        self.risk.emit('MUSIC: Stopped')