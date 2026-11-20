"""Azure Speech text-to-speech (FR-6). Keeps one synthesizer and connection warm; audio plays as it streams."""
from __future__ import annotations

import logging
import threading
import time

from .config import env

log = logging.getLogger(__name__)


class AzureSpeaker:
    def __init__(self, voice: str, key: str | None = None, region: str | None = None, to_speaker: bool = True) -> None:
        import azure.cognitiveservices.speech as sp

        key = key or env("AZURE_SPEECH_KEY")
        region = region or env("AZURE_SPEECH_REGION")
        if not key or not region:
            raise RuntimeError("AZURE_SPEECH_KEY / AZURE_SPEECH_REGION missing in .env")
        cfg = sp.SpeechConfig(subscription=key, region=region)
        cfg.speech_synthesis_voice_name = voice
        audio = sp.audio.AudioOutputConfig(use_default_speaker=True) if to_speaker else None
        self._sp = sp
        self._synth = sp.SpeechSynthesizer(speech_config=cfg, audio_config=audio)
        self._first_audio: float | None = None
        self._on_first = None
        self._lock = threading.Lock()
        self._synth.synthesizing.connect(self._on_chunk)

    def _on_chunk(self, _evt) -> None:
        if self._first_audio is None:
            self._first_audio = time.perf_counter()
            if self._on_first:
                try:
                    self._on_first(self._first_audio)
                except Exception as e:
                    log.warning("first-audio callback failed: %s", e)

    def warm_up(self) -> None:
        try:
            self._sp.Connection.from_speech_synthesizer(self._synth).open(True)
        except Exception as e:  # warm-up must never stop startup
            log.warning("speech warm-up failed: %s", e)

    def speak(self, text: str, on_first_audio=None) -> float | None:
        """Blocks until the line has been spoken. Calls on_first_audio(perf_counter time) when audio starts.
        Returns that time, or None on failure."""
        with self._lock:
            self._first_audio = None
            self._on_first = on_first_audio
            try:
                result = self._synth.speak_text_async(text).get()
            except Exception as e:
                log.warning("speech failed: %s", e)
                return None
            if result.reason != self._sp.ResultReason.SynthesizingAudioCompleted:
                details = getattr(result, "cancellation_details", None)
                log.warning("speech not completed: %s %s", result.reason, getattr(details, "error_details", ""))
                return self._first_audio if self._first_audio else None
            return self._first_audio

    def stop(self) -> None:
        try:
            self._synth.stop_speaking_async()
        except Exception as e:
            log.warning("stop speaking failed: %s", e)
