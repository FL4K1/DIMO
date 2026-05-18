"""Voice I/O node for Phase 3 audio interface.

Handles:
- Speech-to-text (STT) using Faster-Whisper
- Text-to-speech (TTS) using Piper
- Push-to-talk (PTT) recording with correct keyboard event hooking
- Audio streaming for real-time playback with device routing + fallback
- Diagnostic device enumeration
- VAD scaffold for Phase 3.5

Architecture notes:
- keyboard.hook() is used (not on_press) so BOTH press and release fire.
- All PyAudio resources are closed in finally blocks regardless of exceptions.
- PTT loop has a configurable pre-press timeout to prevent infinite hangs.
- Overflow events are logged (not silently dropped) for observability.
- Device-specific playback falls back to system default on failure.
- record_audio() is unified — record_audio_with_device(device_index=None)
  is the single source of truth for timed recording.
"""

import io
import threading
import time
from contextlib import contextmanager
from typing import Generator, List, Optional, Tuple

import numpy as np

from app.config.logging import logger

# ---------------------------------------------------------------------------
# Optional dependency guards — graceful degradation on missing libs
# ---------------------------------------------------------------------------

try:
    # pyrefly: ignore [missing-import]
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("Faster-Whisper not installed. Speech-to-text unavailable.")

try:
    # pyrefly: ignore [missing-import]
    import piper
    PIPER_AVAILABLE = True
except ImportError:
    PIPER_AVAILABLE = False
    logger.warning("Piper TTS not installed. Text-to-speech unavailable.")

try:
    import pyaudio
    import wave  # noqa: F401 — kept for WAV utilities
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    logger.warning("PyAudio not installed. Microphone input unavailable.")

try:
    # pyrefly: ignore [missing-import]
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False
    logger.warning("Soundfile not installed. Audio file saving unavailable.")

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    logger.warning("keyboard library not installed. Push-to-talk limited.")

try:
    import asyncio
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    logger.warning("edge-tts not installed. Text-to-speech unavailable. Run: pip install edge-tts")

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False
    logger.warning("pyttsx3 not installed. Offline TTS unavailable. Run: pip install pyttsx3")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_RATE: int = 16_000      # 16 kHz — optimal for Whisper
CHUNK_SIZE: int = 4_096        # Frames per PyAudio read; tune for latency
CHANNELS: int = 1              # Mono throughout the pipeline
AUDIO_FORMAT: str = "int16"    # numpy dtype label (matches paInt16)

WHISPER_MODEL: str = "base"    # tiny | base | small | medium | large
WHISPER_DEVICE: str = "cpu"    # Change to "cuda" if GPU available

PTT_MAX_DURATION: int = 60     # Hard cap per recording (seconds)
PTT_WAIT_TIMEOUT: int = 30     # Seconds to wait for key press before giving up
PTT_POLL_INTERVAL: float = 0.01   # Event-poll sleep (10 ms — not busy-wait)


# ---------------------------------------------------------------------------
# PyAudio context manager
# ---------------------------------------------------------------------------

@contextmanager
def _pyaudio_context():
    """Open a PyAudio instance and guarantee termination even on exception.

    Usage::

        with _pyaudio_context() as p:
            stream = p.open(...)
    """
    p = pyaudio.PyAudio()
    try:
        yield p
    finally:
        p.terminate()


# ---------------------------------------------------------------------------
# STT — Speech-to-Text (Faster-Whisper)
# ---------------------------------------------------------------------------

def initialize_whisper() -> Optional["WhisperModel"]:
    """Load the Faster-Whisper model once at startup.

    Returns:
        WhisperModel instance, or None if unavailable / failed.
    """
    if not WHISPER_AVAILABLE:
        logger.error("Faster-Whisper not available — cannot initialize.")
        return None

    try:
        logger.info("Loading Whisper model: %s on %s", WHISPER_MODEL, WHISPER_DEVICE)
        model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE)
        logger.info("✓ Whisper model loaded successfully.")
        return model
    except Exception as exc:
        logger.error("Failed to load Whisper model: %s", exc, exc_info=True)
        return None


def transcribe_audio(
    audio_data: np.ndarray,
    model: Optional["WhisperModel"] = None,
) -> str:
    """Convert a numpy audio array to text using Faster-Whisper.

    Args:
        audio_data: Mono int16 samples at SAMPLE_RATE.
        model: Pre-initialized WhisperModel (initializes lazily if None).

    Returns:
        Transcribed text string, or "ERROR: ..." on failure.
    """
    if not WHISPER_AVAILABLE:
        return "ERROR: Faster-Whisper not installed"

    if model is None:
        model = initialize_whisper()
        if model is None:
            return "ERROR: Could not initialize Whisper"

    if audio_data is None or len(audio_data) == 0:
        return "ERROR: Empty audio data"

    try:
        logger.info("Transcribing %d samples (%.1fs)…",
                    len(audio_data), len(audio_data) / SAMPLE_RATE)

        # Faster-Whisper accepts float32 normalized audio OR file paths.
        # Convert int16 → float32 in [-1, 1] for best compatibility.
        audio_f32 = audio_data.astype(np.float32) / 32768.0

        segments, info = model.transcribe(
            audio_f32,
            language="en",
            beam_size=5,
        )

        full_text = " ".join(seg.text for seg in segments).strip()

        if not full_text:
            logger.warning("No speech detected in audio (duration=%.1fs, lang=%s).",
                           info.duration, info.language)
            return "ERROR: No speech detected"

        logger.info("✓ Transcribed: %.100s", full_text)
        return full_text

    except Exception as exc:
        logger.error("Transcription failed: %s", exc, exc_info=True)
        return f"ERROR: Transcription failed — {exc}"


# ---------------------------------------------------------------------------
# Audio recording — unified implementation
# ---------------------------------------------------------------------------

def record_audio_with_device(
    duration_seconds: int = 5,
    device_index: Optional[int] = None,
    sample_rate: int = SAMPLE_RATE,
) -> Optional[np.ndarray]:
    """Record a fixed-duration clip from an input device.

    This is the canonical timed-recording function.
    ``record_audio()`` is a convenience alias for it.

    Args:
        duration_seconds: Recording length in seconds.
        device_index: PyAudio input device index (None = system default).
        sample_rate: Capture sample rate in Hz.

    Returns:
        Mono int16 numpy array, or None on failure.
    """
    if not PYAUDIO_AVAILABLE:
        logger.error("PyAudio not available — cannot record.")
        return None

    device_label = f"device={device_index}" if device_index is not None else "default device"
    logger.info("Recording %ds from %s at %dHz…", duration_seconds, device_label, sample_rate)

    try:
        with _pyaudio_context() as p:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK_SIZE,
            )
            try:
                frames: List[np.ndarray] = []
                num_chunks = int(sample_rate / CHUNK_SIZE * duration_seconds)

                for _ in range(num_chunks):
                    raw = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    frames.append(np.frombuffer(raw, dtype=np.int16))
            finally:
                stream.stop_stream()
                stream.close()

        if not frames:
            logger.warning("No frames captured.")
            return None

        audio_data = np.concatenate(frames)
        logger.info("✓ Captured %d samples (%.1fs) from %s.",
                    len(audio_data), len(audio_data) / sample_rate, device_label)
        return audio_data

    except OSError as exc:
        logger.error("Recording failed [%s]: %s", device_label, exc, exc_info=True)
        return None
    except Exception as exc:
        logger.error("Unexpected recording error: %s", exc, exc_info=True)
        return None


def record_audio(
    duration_seconds: int = 5,
    sample_rate: int = SAMPLE_RATE,
) -> Optional[np.ndarray]:
    """Convenience alias — record from the system default microphone.

    Delegates entirely to :func:`record_audio_with_device`.
    """
    return record_audio_with_device(
        duration_seconds=duration_seconds,
        device_index=None,
        sample_rate=sample_rate,
    )


# ---------------------------------------------------------------------------
# Push-to-talk recording
# ---------------------------------------------------------------------------

def record_audio_push_to_talk(
    device_index: Optional[int] = None,
    sample_rate: int = SAMPLE_RATE,
    trigger_key: str = "ctrl",
    wait_timeout: int = PTT_WAIT_TIMEOUT,
    max_duration: int = PTT_MAX_DURATION,
) -> Optional[np.ndarray]:
    """Record audio while a key is held down (push-to-talk).

    Design:
    -------
    * ``keyboard.hook()`` receives BOTH press (down) and release (up) events.
      The original ``keyboard.on_press()`` only fires on down — the release
      branch would have never triggered, making PTT never stop.
    * The hook reference is stored and ``keyboard.unhook(hook)`` is called in
      the ``finally`` block. ``remove_all_hotkeys()`` does NOT remove hooks
      added via ``hook()``, which was the source of dangling listeners.
    * A ``wait_timeout`` guards the pre-press idle phase. If the user never
      presses the key within that window, the function returns None cleanly.
    * Audio overflow events are logged at DEBUG level so they appear in
      dimo.log but don't spam the console.
    * A threading.Event drives the recording loop — no busy-wait.

    Args:
        device_index: PyAudio input device index (None = system default).
        sample_rate: Capture sample rate in Hz.
        trigger_key: Key name to hold for recording (e.g. "ctrl", "space").
        wait_timeout: Seconds to wait for the first key press before aborting.
        max_duration: Maximum continuous recording length in seconds.

    Returns:
        Mono int16 numpy array, or None if nothing was recorded / error.
    """
    if not PYAUDIO_AVAILABLE:
        logger.error("PyAudio not available — cannot record.")
        return None

    if not KEYBOARD_AVAILABLE:
        logger.warning(
            "keyboard library unavailable — falling back to 5-second timed recording."
        )
        return record_audio_with_device(5, device_index, sample_rate)

    logger.info(
        "PTT ready: hold [%s] to record (timeout=%ds, max=%ds).",
        trigger_key.upper(), wait_timeout, max_duration,
    )

    # Shared state — touched from both the hook thread and the main thread.
    key_down = threading.Event()   # Set while the trigger key is physically held
    key_released = threading.Event()  # Set when key goes up after recording

    def _on_key_event(event: "keyboard.KeyboardEvent") -> None:
        """Keyboard hook — fires on every key event (press AND release)."""
        if trigger_key.lower() not in event.name.lower():
            return  # Ignore unrelated keys

        if event.event_type == keyboard.KEY_DOWN and not key_down.is_set():
            logger.debug("PTT key_down detected: %s", event.name)
            key_down.set()

        elif event.event_type == keyboard.KEY_UP and key_down.is_set():
            logger.debug("PTT key_up detected: %s", event.name)
            key_down.clear()
            key_released.set()

    # Register the hook — store reference for clean removal
    hook_ref = keyboard.hook(_on_key_event)

    try:
        device_label = f"device={device_index}" if device_index is not None else "default"

        with _pyaudio_context() as p:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK_SIZE,
            )
            try:
                frames: List[np.ndarray] = []
                recording_started = False
                recording_start_time: Optional[float] = None
                wait_deadline = time.monotonic() + wait_timeout

                print(f"  [PTT] Hold [{trigger_key.upper()}] to speak "
                      f"(waiting up to {wait_timeout}s)…")

                # ── Main PTT loop ───────────────────────────────────────────
                while True:
                    now = time.monotonic()

                    # ── Phase 1: Waiting for key press ──────────────────────
                    if not recording_started:
                        if key_down.is_set():
                            recording_started = True
                            recording_start_time = now
                            logger.info("PTT: recording started.")
                            print("  [PTT] Recording…")
                            continue

                        # Timeout guard — don't hang forever
                        if now >= wait_deadline:
                            logger.warning(
                                "PTT: no key press within %ds timeout. Aborting.",
                                wait_timeout,
                            )
                            return None

                        # Drain audio buffer while waiting (prevents overflows
                        # when recording eventually starts)
                        stream.read(CHUNK_SIZE, exception_on_overflow=False)
                        time.sleep(PTT_POLL_INTERVAL)
                        continue

                    # ── Phase 2: Actively recording ─────────────────────────
                    elapsed = now - recording_start_time  # type: ignore[operator]

                    if elapsed >= max_duration:
                        logger.info("PTT: max duration (%ds) reached.", max_duration)
                        break

                    if key_released.is_set():
                        logger.info("PTT: key released after %.1fs.", elapsed)
                        print(f"  [PTT] Stopped after {elapsed:.1f}s.")
                        break

                    raw = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    if len(raw) < CHUNK_SIZE * 2:  # int16 = 2 bytes/sample
                        # Overflow: PyAudio returned fewer bytes than requested
                        logger.debug(
                            "PTT audio overflow — short read (%d bytes, expected %d).",
                            len(raw), CHUNK_SIZE * 2,
                        )
                    frames.append(np.frombuffer(raw, dtype=np.int16))

            finally:
                stream.stop_stream()
                stream.close()

        if not frames:
            logger.warning("PTT: no audio frames captured.")
            return None

        audio_data = np.concatenate(frames)
        logger.info(
            "✓ PTT captured %d samples (%.1fs) from %s.",
            len(audio_data), len(audio_data) / sample_rate, device_label,
        )
        return audio_data

    except OSError as exc:
        logger.error("PTT recording failed (OSError): %s", exc, exc_info=True)
        return None
    except Exception as exc:
        logger.error("PTT unexpected error: %s", exc, exc_info=True)
        return None
    finally:
        # ── Guaranteed cleanup ──────────────────────────────────────────────
        # Unhook ONLY our specific hook — don't nuke other listeners.
        try:
            keyboard.unhook(hook_ref)
            logger.debug("PTT: keyboard hook removed cleanly.")
        except Exception as cleanup_exc:
            logger.warning("PTT: keyboard hook removal failed: %s", cleanup_exc)


# ---------------------------------------------------------------------------
# Device enumeration — shared PyAudio instance
# ---------------------------------------------------------------------------

def _enumerate_devices() -> Tuple[List[dict], List[dict]]:
    """Enumerate PyAudio devices once, return (input_devices, output_devices).

    Centralizes PyAudio init/terminate so callers don't each pay that cost.

    Returns:
        Tuple of (input_device_list, output_device_list), each a list of dicts
        with keys: index, name, channels, default_sample_rate.
    """
    if not PYAUDIO_AVAILABLE:
        return [], []

    inputs: List[dict] = []
    outputs: List[dict] = []

    try:
        with _pyaudio_context() as p:
            count = p.get_device_count()
            default_input = p.get_default_input_device_info().get("index", -1)
            default_output = p.get_default_output_device_info().get("index", -1)

            for i in range(count):
                info = p.get_device_info_by_index(i)
                entry = {
                    "index": i,
                    "name": info["name"],
                    "channels": 0,
                    "default_sample_rate": int(info.get("defaultSampleRate", 0)),
                    "is_default": False,
                }
                if info["maxInputChannels"] > 0:
                    entry["channels"] = info["maxInputChannels"]
                    entry["is_default"] = (i == default_input)
                    inputs.append(dict(entry))
                if info["maxOutputChannels"] > 0:
                    entry["channels"] = info["maxOutputChannels"]
                    entry["is_default"] = (i == default_output)
                    outputs.append(dict(entry))

        logger.info(
            "Device enumeration: %d input(s), %d output(s).", len(inputs), len(outputs)
        )
    except Exception as exc:
        logger.error("Failed to enumerate audio devices: %s", exc, exc_info=True)

    return inputs, outputs


def get_input_devices() -> List[Tuple[int, str]]:
    """Return available microphone devices as (index, name) pairs."""
    inputs, _ = _enumerate_devices()
    return [(d["index"], d["name"]) for d in inputs]


def get_output_devices() -> List[Tuple[int, str]]:
    """Return available speaker/output devices as (index, name) pairs."""
    _, outputs = _enumerate_devices()
    return [(d["index"], d["name"]) for d in outputs]


# ---------------------------------------------------------------------------
# TTS — Text-to-Speech (edge-tts)
#
# Why edge-tts instead of piper:
#   piper-tts requires manually downloaded .onnx model files before it can
#   speak a single word.  edge-tts works out-of-the-box with zero local
#   model files and produces high-quality Microsoft Neural voices.
#   Piper will be wired in Phase 3.5 once model management is added.
#
# Pipeline:
#   text → edge_tts.Communicate.save() → temp .mp3
#        → ffmpeg                       → temp .wav  (SAMPLE_RATE, mono)
#        → strip 44-byte WAV header     → raw int16 PCM
#        → yield CHUNK_SIZE chunks      → PyAudio playback
# ---------------------------------------------------------------------------

# Microsoft Neural voice — change to taste.
# Full list: python -m edge_tts --list-voices
EDGE_TTS_VOICE: str = "en-US-ChristopherNeural"


def _edge_tts_to_pcm(text: str, voice: str = EDGE_TTS_VOICE) -> bytes:
    """Synthesize text with edge-tts and return raw int16 PCM bytes.

    Runs the async edge-tts API synchronously via asyncio.run(), converts
    the MP3 output to WAV using ffmpeg, then strips the RIFF header.

    Args:
        text:  Text to synthesize.
        voice: Microsoft Neural voice name.

    Returns:
        Raw int16 PCM bytes at SAMPLE_RATE / mono, or b"" on failure.
    """
    import os
    import subprocess
    import tempfile

    async def _synthesize() -> str:
        """Save edge-tts MP3 output to a temp file; return its path."""
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(tmp.name)
        return tmp.name

    mp3_path = None
    wav_path = None
    try:
        mp3_path = asyncio.run(_synthesize())
        wav_path = mp3_path.replace(".mp3", ".wav")

        # Convert MP3 → WAV at the exact sample rate Whisper / PyAudio expect
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "quiet",
                "-i", mp3_path,
                "-ar", str(SAMPLE_RATE),   # resample to 16 000 Hz
                "-ac", "1",                 # mono
                "-f", "wav",
                wav_path,
            ],
            capture_output=True,
            timeout=30,
        )

        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")[:300]
            logger.error("[TTS] ffmpeg conversion failed: %s", err)
            return b""

        with open(wav_path, "rb") as fh:
            wav_bytes = fh.read()

        # Standard PCM WAV header is exactly 44 bytes — strip it.
        RIFF_HEADER = 44
        if len(wav_bytes) <= RIFF_HEADER:
            logger.error("[TTS] WAV output too short (%d bytes).", len(wav_bytes))
            return b""

        return wav_bytes[RIFF_HEADER:]

    finally:
        for p in (mp3_path, wav_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def synthesize_speech(text: str) -> Generator[bytes, None, None]:
    """Convert text to raw PCM audio and yield chunks for PyAudio playback.

    Primary TTS engine: edge-tts (Microsoft Neural voices, no model files).
    Falls back to silence with an actionable error if edge-tts / ffmpeg
    are unavailable, so the pipeline degrades gracefully.

    Args:
        text: Text to synthesize.

    Yields:
        Raw int16 PCM bytes in CHUNK_SIZE * 2 -byte pieces (2 bytes/sample).
    """
    if not text or not text.strip():
        logger.warning("[TTS] synthesize_speech called with empty text.")
        yield b""
        return

    if not EDGE_TTS_AVAILABLE:
        logger.error("[TTS] edge-tts not installed. Run: pip install edge-tts")
        yield b""
        return

    try:
        logger.info("[TTS] Synthesizing via edge-tts (%s): %.60s…", EDGE_TTS_VOICE, text)
        pcm = _edge_tts_to_pcm(text)

        if not pcm:
            logger.error("[TTS] No PCM data returned — synthesis failed.")
            yield b""
            return

        duration = len(pcm) / (SAMPLE_RATE * 2)   # int16 = 2 bytes per sample
        logger.info("[TTS] Synthesis OK — %d bytes (%.1fs).", len(pcm), duration)

        # Yield in chunks matching the PyAudio buffer size
        chunk_bytes = CHUNK_SIZE * 2   # int16 = 2 bytes per sample
        for offset in range(0, len(pcm), chunk_bytes):
            yield pcm[offset : offset + chunk_bytes]

    except FileNotFoundError:
        logger.error(
            "[TTS] ffmpeg not found on PATH.\n"
            "  Install: winget install ffmpeg   (then restart terminal)"
        )
        yield b""
    except Exception as exc:
        logger.error("[TTS] Unexpected synthesis error: %s", exc, exc_info=True)
        yield b""


# ---------------------------------------------------------------------------
# Audio playback
# ---------------------------------------------------------------------------

def play_audio_stream_with_device(
    audio_generator: Generator[bytes, None, None],
    device_index: Optional[int] = None,
) -> bool:
    """Play streaming audio chunks on a specific output device.

    Fallback behavior:
        If ``device_index`` is specified and fails to open, automatically
        retries with the system default output device.

    Args:
        audio_generator: Generator yielding raw PCM bytes (int16, mono).
        device_index: PyAudio output device index (None = system default).

    Returns:
        True if playback completed, False otherwise.
    """
    if not PYAUDIO_AVAILABLE:
        logger.error("PyAudio not available — cannot play audio.")
        return False

    device_label = f"device={device_index}" if device_index is not None else "default"
    logger.info("Starting playback on %s…", device_label)

    # Consume the generator into a buffer so we can retry on a fallback device
    # without exhausting the generator a second time.
    chunks: List[bytes] = list(audio_generator)
    if not any(chunks):
        logger.warning("Audio generator produced no output — skipping playback.")
        return False

    def _attempt_playback(dev_idx: Optional[int], label: str) -> bool:
        """Inner helper — attempt playback on a given device."""
        try:
            with _pyaudio_context() as p:
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=SAMPLE_RATE,
                    output=True,
                    output_device_index=dev_idx,
                    frames_per_buffer=CHUNK_SIZE,
                )
                try:
                    for chunk in chunks:
                        if chunk:
                            stream.write(chunk)
                finally:
                    stream.stop_stream()
                    stream.close()

            logger.info("✓ Playback complete on %s.", label)
            return True

        except OSError as exc:
            logger.error("Playback failed on %s: %s", label, exc)
            return False
        except Exception as exc:
            logger.error("Unexpected playback error on %s: %s", label, exc, exc_info=True)
            return False

    # Primary attempt
    success = _attempt_playback(device_index, device_label)

    # Fallback to default device if a specific device was requested but failed
    if not success and device_index is not None:
        logger.warning(
            "Falling back to system default output device after failure on %s.",
            device_label,
        )
        success = _attempt_playback(None, "default (fallback)")

    return success


def play_audio_stream(audio_generator: Generator[bytes, None, None]) -> bool:
    """Play streaming audio on the system default output device.

    Convenience alias for :func:`play_audio_stream_with_device`.
    """
    return play_audio_stream_with_device(audio_generator, device_index=None)


# ---------------------------------------------------------------------------
# File utilities
# ---------------------------------------------------------------------------

def save_audio_file(
    audio_data: np.ndarray,
    filename: str,
    sample_rate: int = SAMPLE_RATE,
) -> bool:
    """Save a numpy audio array to a WAV file (for debugging / replay).

    Args:
        audio_data: Mono int16 numpy array.
        filename: Output path (e.g. "debug.wav").
        sample_rate: Sample rate in Hz.

    Returns:
        True on success, False otherwise.
    """
    if not SOUNDFILE_AVAILABLE:
        logger.warning("soundfile not available — cannot save audio.")
        return False

    try:
        sf.write(filename, audio_data, sample_rate)
        logger.info("✓ Audio saved to %s.", filename)
        return True
    except Exception as exc:
        logger.error("Failed to save audio to %s: %s", filename, exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# DIMO pipeline integration helpers
# ---------------------------------------------------------------------------

def process_voice_input(
    audio_data: np.ndarray,
    whisper_model: Optional["WhisperModel"] = None,
) -> str:
    """Transcribe raw microphone audio for injection into the DIMO graph.

    Args:
        audio_data: Raw audio from any record_* function.
        whisper_model: Pre-loaded WhisperModel (lazy-init if None).

    Returns:
        Transcribed text, or "ERROR: …" string.
    """
    if audio_data is None or len(audio_data) == 0:
        return "ERROR: No audio data provided"

    return transcribe_audio(audio_data, whisper_model)


def _speak_pyttsx3(
    text: str,
    output_device_index: Optional[int] = None,
) -> bool:
    """Speak text using pyttsx3 (Windows SAPI) — fully offline, zero external tools.

    Flow:
        pyttsx3.save_to_file() → temp WAV
        wave.open()            → read actual sample_rate (SAPI often outputs 22050 Hz)
        PyAudio stream         → playback at the correct rate

    Why not hardcode SAMPLE_RATE:
        SAMPLE_RATE (16 kHz) is for STT input.  pyttsx3 / SAPI outputs at 22050 Hz
        by default.  Playing 22050 Hz PCM through a 16000 Hz stream produces
        chipmunk audio.  We always read the rate from the WAV header.

    Args:
        text: Text to speak.
        output_device_index: PyAudio device index (None = default).

    Returns:
        True on success, False on any failure.
    """
    import os
    import tempfile
    import wave

    if not PYAUDIO_AVAILABLE:
        logger.error("PyAudio not available — cannot play TTS audio.")
        return False

    wav_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        engine = pyttsx3.init()
        engine.setProperty("rate", 175)   # words per minute
        engine.setProperty("volume", 1.0)
        engine.save_to_file(text, wav_path)
        engine.runAndWait()
        engine.stop()   # release SAPI COM object promptly

        # Read WAV metadata — sample rate comes from the file header
        with wave.open(wav_path, "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()     # bytes per sample: 1, 2, or 4
            pcm_data = wf.readframes(wf.getnframes())

        logger.info(
            "[TTS] pyttsx3 WAV: %d Hz, %d ch, %d-bit, %.1fs",
            sample_rate, n_channels, sampwidth * 8,
            len(pcm_data) / (sample_rate * n_channels * sampwidth),
        )

        # Map sampwidth → PyAudio format constant
        fmt_map = {1: pyaudio.paInt8, 2: pyaudio.paInt16, 4: pyaudio.paInt32}
        pa_fmt = fmt_map.get(sampwidth, pyaudio.paInt16)
        chunk_bytes = CHUNK_SIZE * sampwidth * n_channels

        def _attempt(dev_idx: Optional[int], label: str) -> bool:
            try:
                with _pyaudio_context() as p:
                    stream = p.open(
                        format=pa_fmt,
                        channels=n_channels,
                        rate=sample_rate,
                        output=True,
                        output_device_index=dev_idx,
                        frames_per_buffer=CHUNK_SIZE,
                    )
                    try:
                        for offset in range(0, len(pcm_data), chunk_bytes):
                            stream.write(pcm_data[offset : offset + chunk_bytes])
                    finally:
                        stream.stop_stream()
                        stream.close()
                logger.info("[TTS] Playback complete on %s.", label)
                return True
            except OSError as exc:
                logger.error("[TTS] Playback failed on %s: %s", label, exc)
                return False

        label = f"device={output_device_index}" if output_device_index is not None else "default"
        success = _attempt(output_device_index, label)
        if not success and output_device_index is not None:
            logger.warning("[TTS] Falling back to default output device.")
            success = _attempt(None, "default (fallback)")
        return success

    except Exception as exc:
        logger.error("[TTS] pyttsx3 synthesis failed: %s", exc, exc_info=True)
        return False
    finally:
        if wav_path:
            try:
                os.unlink(wav_path)
            except OSError:
                pass


def stream_voice_response(
    text: str,
    output_device_index: Optional[int] = None,
) -> bool:
    """Synthesize and play a DIMO response.

    TTS priority order:
        1. pyttsx3  — offline, Windows SAPI, zero external tools (primary)
        2. edge-tts  — cloud, requires internet + ffmpeg (fallback)

    Args:
        text: Response text from the LLM node.
        output_device_index: Output device index (None = system default).

    Returns:
        True if spoken successfully, False otherwise.
    """
    if not text or not text.strip():
        logger.warning("stream_voice_response: empty text — nothing to speak.")
        return False

    # ── Primary: pyttsx3 (offline, no dependencies) ─────────────────────
    if PYTTSX3_AVAILABLE:
        logger.info("[TTS] Using pyttsx3 (offline SAPI).")
        return _speak_pyttsx3(text, output_device_index)

    # ── Fallback: edge-tts + ffmpeg (cloud) ─────────────────────────
    if EDGE_TTS_AVAILABLE:
        logger.warning("[TTS] pyttsx3 not available — falling back to edge-tts.")
        try:
            audio_gen = synthesize_speech(text)
            return play_audio_stream_with_device(audio_gen, device_index=output_device_index)
        except Exception as exc:
            logger.error("[TTS] edge-tts fallback failed: %s", exc, exc_info=True)
            return False

    logger.error(
        "[TTS] No TTS engine available.\n"
        "  Install pyttsx3 (offline): pip install pyttsx3\n"
        "  Install edge-tts (cloud):  pip install edge-tts"
    )
    return False


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def check_audio_devices() -> dict:
    """Return a capability snapshot for startup validation.

    Consumed by main.py's ``main_voice()`` to gate on required libraries.

    Returns:
        Dict with keys:
            whisper_available, piper_available, pyaudio_available,
            soundfile_available, keyboard_available,
            input_devices, output_devices
    """
    inputs, outputs = _enumerate_devices()

    report = {
        "whisper_available": WHISPER_AVAILABLE,
        "piper_available": PIPER_AVAILABLE,
        "pyaudio_available": PYAUDIO_AVAILABLE,
        "soundfile_available": SOUNDFILE_AVAILABLE,
        "keyboard_available": KEYBOARD_AVAILABLE,
        "input_devices": inputs,
        "output_devices": outputs,
    }

    # Surface summary to log for observability
    logger.info(
        "Audio capability check — Whisper:%s Piper:%s PyAudio:%s Keyboard:%s | "
        "inputs:%d outputs:%d",
        WHISPER_AVAILABLE, PIPER_AVAILABLE, PYAUDIO_AVAILABLE, KEYBOARD_AVAILABLE,
        len(inputs), len(outputs),
    )

    return report


# ---------------------------------------------------------------------------
# VAD scaffold — Phase 3.5 placeholder
# ---------------------------------------------------------------------------

def detect_speech_vad(
    audio_chunk: np.ndarray,
    threshold: float = 0.5,
    sample_rate: int = SAMPLE_RATE,
) -> bool:
    """Voice Activity Detection hook — scaffold for Silero VAD integration.

    Phase 3.5 will replace this stub with a real Silero VAD call.
    Current behavior: energy-based threshold as a crude approximation.

    Args:
        audio_chunk: Short audio window (e.g. 512 samples).
        threshold: Energy threshold normalized to [0, 1].
        sample_rate: Sample rate (unused until Silero integration).

    Returns:
        True if speech energy exceeds threshold, False otherwise.
    """
    if audio_chunk is None or len(audio_chunk) == 0:
        return False

    # Simple RMS energy check — replace with Silero in Phase 3.5
    rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2)) / 32768.0
    is_speech = rms > threshold

    logger.debug("VAD stub: rms=%.4f threshold=%.4f speech=%s", rms, threshold, is_speech)
    return is_speech
