"""
Gemini Speech Services for Mark-LV Local LLM Mode.

Provides dedicated cloud speech-to-text (STT) and text-to-speech (TTS) services
using Google GenAI APIs, without reintroducing Gemini as a conversational LLM.

- Speech-to-Text: Uses 'gemini-3.5-transcribe-live' exclusively for streaming audio
  transcription (modalities=['TEXT']). No conversational model, tools, or system prompts.
- Text-to-Speech: Uses 'gemini-3.8-flash-lite-tts' (fallback: 'gemini-3.8-flash-tts')
  to speak Ollama's completed text response aloud.
- Conversational Reasoning: Exclusively handled by local Ollama via LocalTurnCoordinator.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import uuid
import wave
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger("marklv.gemini_voice")

# Dedicated speech models
DEFAULT_STT_MODEL = "gemini-3.5-transcribe-live"
DEFAULT_TTS_MODEL = "gemini-3.8-flash-lite-tts"
FALLBACK_TTS_MODEL = "gemini-3.8-flash-tts"
DEFAULT_VOICE = "Charon"

# Audio constants matching Mark-LV hardware streams
SEND_SAMPLE_RATE = 16000     # Microphone sample rate
RECEIVE_SAMPLE_RATE = 24000  # Speaker playback sample rate
PCM_CHANNELS = 1             # Mono audio
TTS_CHUNK_BYTES = 2400       # ~50 ms at 24 kHz 16-bit mono (24000 * 2 * 0.05)


class VoiceStatus(str, Enum):
    UNAVAILABLE = "Voice unavailable"
    CONNECTING = "Connecting transcription"
    READY = "Voice ready"
    IDLE = "Voice ready"
    LISTENING = "Listening"
    TRANSCRIBING = "Transcribing"
    PROCESSING = "Processing locally"
    SPEAKING = "Speaking"
    LOCAL_INFERENCE_FAILED = "Local inference failed"
    ERROR = "Voice error"


def unwrap_exceptions(exc: BaseException) -> List[BaseException]:
    """Recursively extract underlying leaf exceptions from (Base)ExceptionGroup."""
    if isinstance(exc, BaseExceptionGroup):
        res: List[BaseException] = []
        for sub in exc.exceptions:
            res.extend(unwrap_exceptions(sub))
        return res
    return [exc]


def is_benign_closure(exc: BaseException) -> bool:
    """Check if an exception represents normal or benign connection closure / cancellation."""
    leaves = unwrap_exceptions(exc)
    for e in leaves:
        if isinstance(e, asyncio.CancelledError):
            continue
        cls_name = type(e).__name__.lower()
        msg = str(e).lower()
        if "connectionclosedok" in cls_name:
            continue
        if "1000" in msg or "normal closure" in msg or "going away" in msg or "keepalive ping timeout" in msg:
            continue
        return False
    return True


def format_clean_error(exc: BaseException, extra_secret: Optional[str] = None) -> str:
    """Extract a user-readable, sanitized error description from an exception or ExceptionGroup."""
    leaves = unwrap_exceptions(exc)
    meaningful = [e for e in leaves if not isinstance(e, asyncio.CancelledError)]
    if not meaningful:
        meaningful = leaves

    msgs: List[str] = []
    for e in meaningful:
        m = str(e).strip()
        if not m or "sub-exception" in m.lower():
            m = type(e).__name__
        msgs.append(m)

    combined = "; ".join(dict.fromkeys(msgs))
    return redact_secrets(combined or type(exc).__name__, extra_secret)


def redact_secrets(text: str, extra_secret: Optional[str] = None) -> str:
    """Scrub potential API keys and credential tokens from logs and errors."""
    if not text:
        return ""
    s = str(text)
    if extra_secret and len(extra_secret) > 4:
        s = s.replace(extra_secret, "[REDACTED]")
    # Google API keys format: AIzaSy... (39 chars)
    s = re.sub(r'AIza[0-9A-Za-z-_]{35}', '[REDACTED]', s)
    # Generic key patterns
    s = re.sub(
        r'((?:key|api_key|token|secret|password)[=:\s]+)([A-Za-z0-9_\-\.]{8,})',
        r'\1[REDACTED]',
        s,
        flags=re.IGNORECASE
    )
    return s


def decode_wav_to_pcm24k(data: bytes) -> bytes:
    """
    Decode WAV or raw PCM audio bytes to 24000 Hz 16-bit mono PCM.
    Performs in-memory parsing and linear resampling without writing to disk.
    """
    if not data:
        return b""

    # Check if data contains a RIFF/WAV header
    if data.startswith(b"RIFF") and len(data) >= 44:
        try:
            with wave.open(io.BytesIO(data), "rb") as wf:
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                src_rate = wf.getframerate()
                raw_frames = wf.readframes(wf.getnframes())

            if sampwidth == 2:
                samples = np.frombuffer(raw_frames, dtype=np.int16)
            elif sampwidth == 4:
                samples = (np.frombuffer(raw_frames, dtype=np.int32) >> 16).astype(np.int16)
            elif sampwidth == 1:
                samples = ((np.frombuffer(raw_frames, dtype=np.uint8).astype(np.int16) - 128) << 8).astype(np.int16)
            else:
                samples = np.frombuffer(raw_frames, dtype=np.int16)

            if n_channels > 1:
                samples = samples.reshape(-1, n_channels).mean(axis=1).astype(np.int16)

            if src_rate != RECEIVE_SAMPLE_RATE and len(samples) > 1:
                target_len = int(round(len(samples) * RECEIVE_SAMPLE_RATE / src_rate))
                orig_indices = np.linspace(0, len(samples) - 1, len(samples))
                target_indices = np.linspace(0, len(samples) - 1, target_len)
                samples = np.interp(target_indices, orig_indices, samples).astype(np.int16)

            return samples.tobytes()
        except Exception as e:
            logger.debug("Failed to decode as WAV, falling back to raw PCM: %s", e)

    # Fallback: assume already 24kHz int16 PCM (or truncate odd byte)
    if len(data) % 2 != 0:
        data = data[:-1]
    return data


@dataclass
class GeminiVoiceConfig:
    stt_model: str = DEFAULT_STT_MODEL
    tts_model: str = DEFAULT_TTS_MODEL
    tts_fallback_model: str = FALLBACK_TTS_MODEL
    voice_name: str = DEFAULT_VOICE
    sample_rate_in: int = SEND_SAMPLE_RATE
    sample_rate_out: int = RECEIVE_SAMPLE_RATE
    max_turn_wait_seconds: float = 10.0


class GeminiTranscriber:
    """
    Dedicated streaming audio transcriber using gemini-3.5-transcribe-live.
    Handles microphone audio ingestion, live websocket streaming, and
    turn-deduplicated transcript events.
    """

    def __init__(
        self,
        client: Any,
        config: Optional[GeminiVoiceConfig] = None,
        on_interim: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[str, int], None]] = None,
        on_status: Optional[Callable[[VoiceStatus, Optional[str]], None]] = None,
    ):
        self._client = client
        self._config = config or GeminiVoiceConfig()
        self.on_interim = on_interim
        self.on_final = on_final
        self.on_status = on_status

        self._active_session_id: Optional[str] = None
        self._current_turn_id: int = 0
        self._turn_committed: bool = False
        self._is_listening: bool = False
        self._audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        self._session_stop_event = asyncio.Event()
        self._running_task: Optional[asyncio.Task] = None

    @property
    def is_listening(self) -> bool:
        return self._is_listening

    @property
    def current_turn_id(self) -> int:
        return self._current_turn_id

    def start_listening(self) -> int:
        """Begin a new spoken utterance (e.g. push-to-talk press)."""
        self._current_turn_id += 1
        self._turn_committed = False
        self._is_listening = True
        # Drain any residual queued audio from a prior turn
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except Exception:
                break

        if self.on_status:
            self.on_status(VoiceStatus.LISTENING, None)
        return self._current_turn_id

    def feed_audio(self, pcm_data: bytes) -> None:
        """Enqueue PCM microphone audio chunk if currently listening."""
        if not self._is_listening or not pcm_data:
            return
        try:
            self._audio_queue.put_nowait(pcm_data)
        except Exception as e:
            logger.debug("Failed to enqueue mic audio: %s", e)

    def stop_listening(self) -> None:
        """Conclude speech input (e.g. push-to-talk release)."""
        if not self._is_listening:
            return
        self._is_listening = False
        # Send end-of-audio sentinel
        try:
            self._audio_queue.put_nowait(None)
        except Exception:
            pass

        if self.on_status:
            self.on_status(VoiceStatus.TRANSCRIBING, None)

    async def run_session(self, stop_event: asyncio.Event) -> None:
        """
        Maintain the live transcription streaming session until stop_event is set.
        Reconnects on transient network drops.
        """
        try:
            from google.genai import types
        except ImportError:
            if self.on_status:
                self.on_status(VoiceStatus.UNAVAILABLE, "google-genai SDK not installed")
            return

        while not stop_event.is_set():
            session_id = str(uuid.uuid4())
            self._active_session_id = session_id
            if self.on_status:
                self.on_status(VoiceStatus.CONNECTING, None)

            # Strictly configure speech-to-text ONLY with response_modalities=["TEXT"]
            live_config = types.LiveConnectConfig(
                response_modalities=["TEXT"],
                input_audio_transcription=types.AudioTranscriptionConfig(
                    language_codes=[],
                ),
            )

            session_done = asyncio.Event()

            async def _run_send(s: Any, s_id: str) -> None:
                try:
                    await self._send_loop(s, s_id, stop_event, session_done)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    if not is_benign_closure(e):
                        raise
                finally:
                    session_done.set()

            async def _run_recv(s: Any, s_id: str) -> None:
                try:
                    await self._recv_loop(s, s_id, stop_event, session_done)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    if not is_benign_closure(e):
                        raise
                finally:
                    session_done.set()

            try:
                async with self._client.aio.live.connect(
                    model=self._config.stt_model,
                    config=live_config,
                ) as session:
                    if self.on_status:
                        self.on_status(VoiceStatus.READY, None)

                    # Sub-tasks: streamer and receiver coordinated via session_done
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(_run_send(session, session_id))
                        tg.create_task(_run_recv(session, session_id))

            except asyncio.CancelledError:
                break
            except Exception as e:
                if is_benign_closure(e):
                    logger.debug("Transcription session closed/reconnected cleanly: %s", format_clean_error(e))
                else:
                    safe_err = format_clean_error(e, self._config.stt_model)
                    logger.warning("Transcription session error: %s", safe_err)
                    if self.on_status:
                        self.on_status(VoiceStatus.ERROR, safe_err)
                if stop_event.is_set():
                    break
                await asyncio.sleep(1.0)
            finally:
                if self._active_session_id == session_id:
                    self._active_session_id = None

    async def _send_loop(
        self,
        session: Any,
        session_id: str,
        stop_event: asyncio.Event,
        session_done: asyncio.Event,
    ) -> None:
        from google.genai import types

        while not stop_event.is_set() and not session_done.is_set() and self._active_session_id == session_id:
            try:
                chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue

            if session_done.is_set() or stop_event.is_set():
                break

            if chunk is None:
                # Signal end of user audio stream for this turn
                try:
                    await session.send_realtime_input(audio_stream_end=True)
                except Exception as e:
                    logger.debug("Failed sending audio_stream_end: %s", redact_secrets(str(e)))
                continue

            try:
                await session.send_realtime_input(
                    audio=types.Blob(
                        data=chunk,
                        mime_type=f"audio/pcm;rate={self._config.sample_rate_in}",
                    )
                )
            except Exception as e:
                logger.debug("Failed sending audio chunk: %s", redact_secrets(str(e)))
                break

    async def _recv_loop(
        self,
        session: Any,
        session_id: str,
        stop_event: asyncio.Event,
        session_done: asyncio.Event,
    ) -> None:
        try:
            async for response in session.receive():
                if stop_event.is_set() or session_done.is_set() or self._active_session_id != session_id:
                    break

                server_content = getattr(response, "server_content", None)
                if not server_content:
                    continue

                # Check interim transcription
                interim = getattr(server_content, "interim_input_transcription", None)
                if interim and getattr(interim, "text", None):
                    text = interim.text.strip()
                    if text and self.on_interim:
                        self.on_interim(text)

                # Check final committed transcription
                final = getattr(server_content, "input_transcription", None)
                if final and getattr(final, "text", None):
                    text = final.text.strip()
                    if text and not self._turn_committed:
                        self._turn_committed = True
                        if self.on_status:
                            self.on_status(VoiceStatus.PROCESSING, None)
                        if self.on_final:
                            self.on_final(text, self._current_turn_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not is_benign_closure(e):
                raise


class GeminiTTS:
    """
    Dedicated Text-to-Speech synthesis service using Gemini 3.8 Flash TTS.
    Converts completed text into 24000 Hz 16-bit mono PCM.
    """

    def __init__(
        self,
        client: Any,
        config: Optional[GeminiVoiceConfig] = None,
    ):
        self._client = client
        self._config = config or GeminiVoiceConfig()

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
    ) -> bytes:
        """
        Synthesize text into 24 kHz mono 16-bit PCM bytes.
        Returns empty bytes if text is empty.
        """
        clean_text = str(text or "").strip()
        if not clean_text:
            return b""

        selected_voice = voice or self._config.voice_name
        models_to_try = [self._config.tts_model, self._config.tts_fallback_model]
        last_error = None

        for model_name in models_to_try:
            try:
                # Call Gemini TTS API
                interaction = await self._client.aio.interactions.create(
                    model=model_name,
                    input=[{
                        "type": "user_input",
                        "content": [{
                            "type": "text",
                            "text": clean_text,
                        }],
                    }],
                    response_format={"type": "audio"},
                    generation_config={
                        "speech_config": [
                            {"voice": selected_voice},
                        ]
                    },
                )

                output_audio = getattr(interaction, "output_audio", None)
                if not output_audio or not getattr(output_audio, "data", None):
                    raise ValueError(f"TTS response from model '{model_name}' contained no audio data.")

                raw_b64 = output_audio.data
                wav_bytes = base64.b64decode(raw_b64)
                return decode_wav_to_pcm24k(wav_bytes)

            except Exception as e:
                last_error = e
                safe_err = redact_secrets(str(e))
                logger.warning("TTS generation with '%s' failed: %s", model_name, safe_err)
                # Try fallback model if available
                continue

        safe_last_err = redact_secrets(str(last_error))
        raise RuntimeError(f"All TTS models failed to synthesize audio: {safe_last_err}") from last_error


class GeminiVoiceService:
    """
    High-level voice coordination service for Local LLM Mode.
    Connects GeminiTranscriber and GeminiTTS with Mark-LV UI and audio queues.
    Guarantees:
    - Never passes speech to a conversational cloud model.
    - Submits recognized transcript strictly to the local Ollama turn coordinator.
    - Speaks Ollama's final response text unchanged.
    - Deduplicates turns and ignores stale callbacks.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
        config: Optional[GeminiVoiceConfig] = None,
        ui_logger: Optional[Callable[[str], None]] = None,
    ):
        self._api_key = api_key.strip() if api_key and isinstance(api_key, str) else None
        self._config = config or GeminiVoiceConfig()
        self._ui_logger = ui_logger
        self._status: VoiceStatus = VoiceStatus.UNAVAILABLE
        self._is_available: bool = False

        self._on_transcript_callback: Optional[Callable[[str], None]] = None
        self._on_status_callback: Optional[Callable[[VoiceStatus, Optional[str]], None]] = None
        self._committed_turn_ids: set[int] = set()
        self._stop_event = asyncio.Event()
        self._runner_task: Optional[asyncio.Task] = None

        # Initialize GenAI client
        if client is not None:
            self._client = client
            self._is_available = True
            self._status = VoiceStatus.IDLE
        elif self._api_key and len(self._api_key) > 15:
            try:
                from google import genai
                self._client = genai.Client(api_key=self._api_key)
                self._is_available = True
                self._status = VoiceStatus.IDLE
            except Exception as e:
                logger.warning("Failed to initialize GenAI client: %s", redact_secrets(str(e)))
                self._client = None
                self._is_available = False
                self._status = VoiceStatus.UNAVAILABLE
        else:
            self._client = None
            self._is_available = False
            self._status = VoiceStatus.UNAVAILABLE

        # Subcomponents
        if self._is_available and self._client:
            self._transcriber = GeminiTranscriber(
                client=self._client,
                config=self._config,
                on_interim=self._handle_interim_transcript,
                on_final=self._handle_final_transcript,
                on_status=self._handle_transcriber_status,
            )
            self._tts = GeminiTTS(
                client=self._client,
                config=self._config,
            )
        else:
            self._transcriber = None
            self._tts = None

    @property
    def is_available(self) -> bool:
        return self._is_available

    @property
    def status(self) -> VoiceStatus:
        return self._status

    @property
    def is_listening(self) -> bool:
        return bool(self._transcriber and self._transcriber.is_listening)

    def set_transcript_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback to receive final recognized transcript for local turn coordinator."""
        self._on_transcript_callback = callback

    def set_status_callback(self, callback: Callable[[VoiceStatus, Optional[str]], None]) -> None:
        """Set callback to receive voice lifecycle status changes."""
        self._on_status_callback = callback

    def _log_ui(self, msg: str) -> None:
        if self._ui_logger:
            try:
                self._ui_logger(msg)
            except Exception:
                pass

    def _handle_interim_transcript(self, text: str) -> None:
        logger.debug("Interim transcript: %s", text)

    def _handle_final_transcript(self, text: str, turn_id: int) -> None:
        """Invoked when the speech service commits a completed transcript."""
        clean_text = text.strip()
        if not clean_text:
            return

        # Deduplication: ensure each turn is dispatched exactly once
        if turn_id in self._committed_turn_ids:
            logger.debug("Ignoring duplicate final transcript for turn %d: %s", turn_id, clean_text)
            return

        self._committed_turn_ids.add(turn_id)
        # Cap memory of seen turn IDs
        if len(self._committed_turn_ids) > 100:
            self._committed_turn_ids = set(list(self._committed_turn_ids)[-50:])

        logger.info("Committed spoken turn %d: %s", turn_id, clean_text)
        if self._on_transcript_callback:
            try:
                self._on_transcript_callback(clean_text)
            except Exception as e:
                logger.error("Error dispatching transcript to turn coordinator: %s", e)

    def _handle_transcriber_status(self, status: VoiceStatus, message: Optional[str]) -> None:
        self._status = status
        if getattr(self, "_on_status_callback", None):
            try:
                self._on_status_callback(status, message)
            except Exception:
                pass
        if message and status == VoiceStatus.ERROR:
            self._log_ui(f"SYS: {status.value} — {message}")

    def start_listening(self) -> Optional[int]:
        """Handle PTT press. Returns turn_id if available."""
        if not self._is_available or not self._transcriber:
            self._log_ui("SYS: Voice is unavailable (Gemini credentials not configured). Please type your message.")
            return None
        self._status = VoiceStatus.LISTENING
        if getattr(self, "_on_status_callback", None):
            try:
                self._on_status_callback(VoiceStatus.LISTENING, None)
            except Exception:
                pass
        return self._transcriber.start_listening()

    def feed_audio(self, data: bytes) -> None:
        """Feed microphone PCM chunk."""
        if self._transcriber and self._is_available:
            self._transcriber.feed_audio(data)

    def stop_listening(self) -> None:
        """Handle PTT release."""
        if self._transcriber and self._is_available:
            self._transcriber.stop_listening()
            self._status = VoiceStatus.TRANSCRIBING
            if getattr(self, "_on_status_callback", None):
                try:
                    self._on_status_callback(VoiceStatus.TRANSCRIBING, None)
                except Exception:
                    pass

    async def speak(
        self,
        reply: str,
        audio_in_queue: asyncio.Queue,
        turn_done_event: asyncio.Event,
        ui_logger: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Synthesize Ollama's final response and queue PCM chunks into audio_in_queue.
        Returns True on successful playback queuing, False on failure.
        """
        clean_reply = str(reply or "").strip()
        if not clean_reply or not self._is_available or not self._tts:
            return False

        self._status = VoiceStatus.SPEAKING
        log_fn = ui_logger or self._log_ui

        try:
            pcm_bytes = await self._tts.synthesize(clean_reply)
            if not pcm_bytes:
                return False

            # Slice into ~50 ms chunks and feed into Mark-LV's existing audio_in_queue
            idx = 0
            while idx < len(pcm_bytes):
                chunk = pcm_bytes[idx : idx + TTS_CHUNK_BYTES]
                idx += TTS_CHUNK_BYTES
                await audio_in_queue.put(chunk)

            # Signal turn completion so speaker finishes and resets state
            turn_done_event.set()
            return True

        except Exception as e:
            safe_err = redact_secrets(str(e), self._api_key)
            logger.warning("TTS speech output failed: %s", safe_err)
            log_fn(f"SYS: Voice output error: {safe_err}")
            self._status = VoiceStatus.IDLE
            return False

    async def run_loop(self) -> None:
        """Run the background transcription session loop."""
        if not self._is_available or not self._transcriber:
            return
        self._stop_event.clear()
        await self._transcriber.run_session(self._stop_event)

    def stop(self) -> None:
        """Stop background tasks and cancel active sessions."""
        self._stop_event.set()
        if self._transcriber:
            self._transcriber.stop_listening()
        self._status = VoiceStatus.IDLE if self._is_available else VoiceStatus.UNAVAILABLE
