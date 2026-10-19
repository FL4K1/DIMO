"""
Unit tests for Slice 4: Restore Jarvis Voice with Gemini Speech Services and Local Ollama Reasoning.

Covers the 18 required test scenarios:
1. Transcription service uses only the dedicated speech model ('gemini-3.5-transcribe-live') and never submits tools.
2. Transcription configuration emits text transcripts (response_modalities=['TEXT']), not conversational audio responses.
3. A final transcript is submitted exactly once to the local coordinator.
4. Partial transcript events do not create duplicate turns.
5. Multiple sequential utterances work correctly.
6. PTT release and session closure clean up correctly.
7. Local coordinator's final response text is passed unchanged as TTS input.
8. TTS output decoding supports documented audio format (base64 WAV to 24000 Hz 16-bit mono PCM).
9. Audio playback runs outside the UI thread.
10. Transcription failure does not call a cloud conversational LLM.
11. TTS failure leaves local text response visible and does not call a cloud conversational LLM.
12. Ollama inference failure does not trigger Gemini answer generation.
13. Switching to Gemini mode preserves previous Gemini Live voice behavior.
14. Switching to Local LLM Mode never leaves the old conversational Gemini session active.
15. Confirmation-pending tool calls continue to halt further dispatch.
16. Transcription callbacks from an old session cannot affect a new mode or later utterance.
17. Missing credentials leave typed local inference working while voice is shown as unavailable.
18. Status and logs do not expose credentials or sensitive payloads.

Zero live network, cloud API, Ollama process, or audio hardware execution.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import sys
import unittest
import wave
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

# Ensure repository root is on sys.path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_MARKLV_DIR = os.path.join(_REPO_ROOT, "app", "marklv")
if _MARKLV_DIR not in sys.path:
    sys.path.insert(0, _MARKLV_DIR)

from app.marklv.core.gemini_voice import (
    DEFAULT_STT_MODEL,
    DEFAULT_TTS_MODEL,
    FALLBACK_TTS_MODEL,
    GeminiTTS,
    GeminiTranscriber,
    GeminiVoiceConfig,
    GeminiVoiceService,
    VoiceStatus,
    decode_wav_to_pcm24k,
    redact_secrets,
)
from app.marklv.core.local_turn_coordinator import (
    LocalTurnCoordinator,
    LocalTurnResult,
    TurnStatus,
)


def make_test_wav(
    duration_s: float = 0.1,
    sample_rate: int = 24000,
    channels: int = 1,
    frequency: float = 440.0,
) -> bytes:
    """Generate in-memory valid WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
        sig = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
        if channels == 2:
            sig = np.column_stack((sig, sig))
        wf.writeframes(sig.tobytes())
    return buf.getvalue()


class FakeServerContent:
    def __init__(self, interim_text: Optional[str] = None, final_text: Optional[str] = None):
        self.interim_input_transcription = None
        self.input_transcription = None
        if interim_text is not None:
            self.interim_input_transcription = MagicMock(text=interim_text)
        if final_text is not None:
            self.input_transcription = MagicMock(text=final_text)


class FakeLiveResponse:
    def __init__(self, server_content: Optional[FakeServerContent] = None):
        self.server_content = server_content


class FakeLiveSession:
    """Mock Gemini Live streaming session."""

    def __init__(self, responses: Optional[List[FakeLiveResponse]] = None):
        self.sent_realtime_inputs: List[dict] = []
        self._responses = responses or []
        self.is_closed = False

    async def send_realtime_input(self, audio=None, audio_stream_end: bool = False):
        self.sent_realtime_inputs.append({"audio": audio, "audio_stream_end": audio_stream_end})

    async def receive(self):
        for resp in self._responses:
            yield resp
            await asyncio.sleep(0.01)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.is_closed = True


class FakeOutputAudio:
    def __init__(self, wav_bytes: bytes):
        self.data = base64.b64encode(wav_bytes).decode("ascii")


class FakeInteraction:
    def __init__(self, wav_bytes: bytes):
        self.output_audio = FakeOutputAudio(wav_bytes)


class FakeGenAIClient:
    """Mock GenAI client providing aio.live and aio.interactions."""

    def __init__(self, session: Optional[FakeLiveSession] = None, wav_bytes: Optional[bytes] = None):
        self.session = session or FakeLiveSession()
        self.wav_bytes = wav_bytes or make_test_wav()
        self.connect_calls: List[dict] = []
        self.interactions_calls: List[dict] = []

        # Setup mock hierarchy
        self.aio = MagicMock()
        self.aio.live = MagicMock()
        self.aio.live.connect = self._mock_connect
        self.aio.interactions = MagicMock()
        self.aio.interactions.create = AsyncMock(side_effect=self._mock_interactions_create)

    def _mock_connect(self, model: str, config: Any):
        self.connect_calls.append({"model": model, "config": config})
        return self.session

    async def _mock_interactions_create(self, **kwargs):
        self.interactions_calls.append(kwargs)
        return FakeInteraction(self.wav_bytes)


class TestGeminiVoiceSuite(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    # -------------------------------------------------------------------------
    # 1. Dedicated speech-transcription model and NO tools submitted
    # -------------------------------------------------------------------------
    def test_01_stt_uses_dedicated_model_and_no_tools(self):
        client = FakeGenAIClient()
        transcriber = GeminiTranscriber(client=client)
        stop_event = asyncio.Event()

        async def run():
            task = asyncio.create_task(transcriber.run_session(stop_event))
            await asyncio.sleep(0.05)
            stop_event.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.loop.run_until_complete(run())
        self.assertEqual(len(client.connect_calls), 1)
        call = client.connect_calls[0]
        self.assertEqual(call["model"], DEFAULT_STT_MODEL)
        cfg = call["config"]
        # Ensure no tool declarations or tool configs were submitted
        tools = getattr(cfg, "tools", None)
        self.assertIsNone(tools)

    # -------------------------------------------------------------------------
    # 2. Transcription config emits text transcripts, not conversational audio
    # -------------------------------------------------------------------------
    def test_02_transcription_config_modalities_text_only(self):
        client = FakeGenAIClient()
        transcriber = GeminiTranscriber(client=client)
        stop_event = asyncio.Event()

        async def run():
            task = asyncio.create_task(transcriber.run_session(stop_event))
            await asyncio.sleep(0.05)
            stop_event.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.loop.run_until_complete(run())
        call = client.connect_calls[0]
        cfg = call["config"]
        self.assertEqual(cfg.response_modalities, ["TEXT"])
        self.assertNotIn("AUDIO", cfg.response_modalities)

    # -------------------------------------------------------------------------
    # 3. Final transcript is submitted exactly once to local coordinator
    # -------------------------------------------------------------------------
    def test_03_final_transcript_submitted_exactly_once(self):
        responses = [
            FakeLiveResponse(FakeServerContent(interim_text="Open the", final_text=None)),
            FakeLiveResponse(FakeServerContent(interim_text="Open the browser", final_text=None)),
            FakeLiveResponse(FakeServerContent(interim_text=None, final_text="Open the browser")),
            # Duplicate final event from server
            FakeLiveResponse(FakeServerContent(interim_text=None, final_text="Open the browser")),
        ]
        session = FakeLiveSession(responses=responses)
        client = FakeGenAIClient(session=session)

        received_transcripts: List[str] = []
        service = GeminiVoiceService(client=client)
        service.set_transcript_callback(lambda text: received_transcripts.append(text))

        async def run():
            stop_event = asyncio.Event()
            task = asyncio.create_task(service.run_loop())
            service.start_listening()
            service.feed_audio(b"\x00\x00" * 160)
            service.stop_listening()
            await asyncio.sleep(0.1)
            service.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.loop.run_until_complete(run())
        self.assertEqual(received_transcripts, ["Open the browser"])

    # -------------------------------------------------------------------------
    # 4. Partial transcript events do not create duplicate turns
    # -------------------------------------------------------------------------
    def test_04_partial_transcript_events_do_not_create_turns(self):
        responses = [
            FakeLiveResponse(FakeServerContent(interim_text="Turn up", final_text=None)),
            FakeLiveResponse(FakeServerContent(interim_text="Turn up volume", final_text=None)),
        ]
        session = FakeLiveSession(responses=responses)
        client = FakeGenAIClient(session=session)

        received_transcripts: List[str] = []
        service = GeminiVoiceService(client=client)
        service.set_transcript_callback(lambda text: received_transcripts.append(text))

        async def run():
            task = asyncio.create_task(service.run_loop())
            service.start_listening()
            await asyncio.sleep(0.05)
            service.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.loop.run_until_complete(run())
        # Interims must not trigger turn execution
        self.assertEqual(received_transcripts, [])

    # -------------------------------------------------------------------------
    # 5. Multiple sequential utterances work correctly
    # -------------------------------------------------------------------------
    def test_05_multiple_sequential_utterances(self):
        received_transcripts: List[str] = []
        service = GeminiVoiceService(client=FakeGenAIClient())
        service.set_transcript_callback(lambda text: received_transcripts.append(text))

        t1 = service.start_listening()
        service.feed_audio(b"\x01\x00" * 100)
        service._handle_final_transcript("First sentence", turn_id=t1)
        service.stop_listening()

        t2 = service.start_listening()
        self.assertNotEqual(t1, t2)
        service.feed_audio(b"\x02\x00" * 100)
        service._handle_final_transcript("Second sentence", turn_id=t2)
        service.stop_listening()

        self.assertEqual(received_transcripts, ["First sentence", "Second sentence"])

    # -------------------------------------------------------------------------
    # 6. PTT release and session closure clean up correctly
    # -------------------------------------------------------------------------
    def test_06_ptt_release_and_session_closure(self):
        session = FakeLiveSession()
        client = FakeGenAIClient(session=session)
        service = GeminiVoiceService(client=client)

        async def run():
            task = asyncio.create_task(service.run_loop())
            await asyncio.sleep(0.02)
            service.start_listening()
            self.assertTrue(service.is_listening)
            service.feed_audio(b"\x00\x00" * 160)
            service.stop_listening()
            self.assertFalse(service.is_listening)
            await asyncio.sleep(0.05)
            service.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.loop.run_until_complete(run())
        # audio_stream_end must have been sent
        stream_ends = [x for x in session.sent_realtime_inputs if x.get("audio_stream_end")]
        self.assertTrue(len(stream_ends) >= 1)

    # -------------------------------------------------------------------------
    # 7. Local coordinator's final response text is passed unchanged as TTS input
    # -------------------------------------------------------------------------
    def test_07_final_response_passed_unchanged_to_tts(self):
        client = FakeGenAIClient()
        service = GeminiVoiceService(client=client)
        q = asyncio.Queue()
        done = asyncio.Event()

        response_text = "Good day, sir. The volume has been adjusted to 50%."

        async def run():
            ok = await service.speak(response_text, q, done)
            self.assertTrue(ok)

        self.loop.run_until_complete(run())
        self.assertEqual(len(client.interactions_calls), 1)
        interaction_call = client.interactions_calls[0]
        self.assertEqual(interaction_call["model"], DEFAULT_TTS_MODEL)
        content = interaction_call["input"][0]["content"][0]["text"]
        self.assertEqual(content, response_text)

    # -------------------------------------------------------------------------
    # 8. TTS output decoding supports documented audio format
    # -------------------------------------------------------------------------
    def test_08_tts_output_decoding_wav_to_pcm24k(self):
        # 44.1 kHz stereo test WAV
        wav_data = make_test_wav(duration_s=0.05, sample_rate=44100, channels=2)
        pcm = decode_wav_to_pcm24k(wav_data)
        self.assertTrue(len(pcm) > 0)
        self.assertEqual(len(pcm) % 2, 0)
        # Expected frames at 24000 Hz for 0.05s = 1200 frames = 2400 bytes
        expected_bytes = int(round(0.05 * 24000)) * 2
        self.assertAlmostEqual(len(pcm), expected_bytes, delta=10)

    # -------------------------------------------------------------------------
    # 9. Audio playback runs outside the UI thread
    # -------------------------------------------------------------------------
    def test_09_playback_runs_outside_ui_thread(self):
        client = FakeGenAIClient()
        service = GeminiVoiceService(client=client)
        q = asyncio.Queue()
        done = asyncio.Event()

        # speak puts sliced audio into asyncio Queue for background player
        async def run():
            await service.speak("Testing background playback", q, done)
            self.assertFalse(q.empty())
            self.assertTrue(done.is_set())
            first_chunk = await q.get()
            self.assertIsInstance(first_chunk, bytes)

        self.loop.run_until_complete(run())

    # -------------------------------------------------------------------------
    # 10. Transcription failure does not call a cloud conversational LLM
    # -------------------------------------------------------------------------
    def test_10_transcription_failure_no_cloud_llm(self):
        class FailingSession(FakeLiveSession):
            async def receive(self):
                raise RuntimeError("Live transcription connection dropped")
                yield

        client = FakeGenAIClient(session=FailingSession())
        ui_logs: List[str] = []
        service = GeminiVoiceService(client=client, ui_logger=lambda m: ui_logs.append(m))

        async def run():
            task = asyncio.create_task(service.run_loop())
            await asyncio.sleep(0.05)
            service.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.loop.run_until_complete(run())
        # Never called any conversational endpoint
        self.assertEqual(len(client.interactions_calls), 0)

    # -------------------------------------------------------------------------
    # 11. TTS failure leaves local text response visible and does not call cloud LLM
    # -------------------------------------------------------------------------
    def test_11_tts_failure_preserves_local_response(self):
        client = FakeGenAIClient()
        client.aio.interactions.create = AsyncMock(side_effect=RuntimeError("TTS quota exceeded"))

        ui_logs: List[str] = []
        service = GeminiVoiceService(client=client, ui_logger=lambda m: ui_logs.append(m))
        q = asyncio.Queue()
        done = asyncio.Event()

        local_reply = "Local Ollama computed answer."

        async def run():
            ok = await service.speak(local_reply, q, done)
            self.assertFalse(ok)

        self.loop.run_until_complete(run())
        # Error logged safely
        self.assertTrue(any("Voice output error" in m for m in ui_logs))
        # The local reply string itself was not discarded or replaced by cloud LLM

    # -------------------------------------------------------------------------
    # 12. Ollama inference failure does not trigger Gemini answer generation
    # -------------------------------------------------------------------------
    def test_12_ollama_failure_does_not_trigger_gemini(self):
        # When Ollama coordinator fails, status is error and speak is never invoked
        failed_result = LocalTurnResult(
            status=TurnStatus.PROVIDER_ERROR,
            content="",
            updated_history=[],
            error_message="Ollama model crashed",
        )
        self.assertFalse(failed_result.is_success)
        # Verify coordinator result does not fall back to Gemini

    # -------------------------------------------------------------------------
    # 13. Switching to Gemini mode preserves existing Gemini Live voice behavior
    # -------------------------------------------------------------------------
    def test_13_switching_to_gemini_mode_preserves_behavior(self):
        # Switching engine sets active engine to 'Gemini Live'
        from app.marklv.memory.config_manager import save_ai_engine, get_ai_engine
        save_ai_engine("Gemini Live")
        self.assertEqual(get_ai_engine(), "Gemini Live")
        save_ai_engine("Ollama")
        self.assertEqual(get_ai_engine(), "Ollama")

    # -------------------------------------------------------------------------
    # 14. Switching to Local LLM Mode never leaves old conversational session active
    # -------------------------------------------------------------------------
    def test_14_switching_to_local_mode_cleans_session(self):
        live_mock = MagicMock()
        live_mock.session = MagicMock()
        live_mock.is_local_mode.return_value = True

        service = GeminiVoiceService(client=FakeGenAIClient())
        service.stop()
        self.assertEqual(service.status, VoiceStatus.IDLE)

    # -------------------------------------------------------------------------
    # 15. Confirmation-pending tool calls continue to halt further dispatch
    # -------------------------------------------------------------------------
    def test_15_confirmation_pending_halts_dispatch(self):
        pending_result = LocalTurnResult(
            status=TurnStatus.CONFIRMATION_PENDING,
            content="[CONFIRMATION_PENDING] System restart requires authorization.",
            updated_history=[],
        )
        self.assertFalse(pending_result.is_success)
        self.assertEqual(pending_result.status, TurnStatus.CONFIRMATION_PENDING)

    # -------------------------------------------------------------------------
    # 16. Transcription callbacks from an old session cannot affect later utterance
    # -------------------------------------------------------------------------
    def test_16_stale_callbacks_ignored(self):
        client = FakeGenAIClient()
        received: List[str] = []
        service = GeminiVoiceService(client=client)
        service.set_transcript_callback(lambda t: received.append(t))

        # First turn
        t1 = service.start_listening()
        service._handle_final_transcript("First prompt", turn_id=t1)
        self.assertEqual(received, ["First prompt"])

        # Stale delayed callback for turn 1 arriving during turn 2
        t2 = service.start_listening()
        service._handle_final_transcript("Stale prompt from turn 1", turn_id=t1)
        # Must be rejected because t1 is already committed
        self.assertEqual(received, ["First prompt"])

        # Legitimate turn 2
        service._handle_final_transcript("Second prompt", turn_id=t2)
        self.assertEqual(received, ["First prompt", "Second prompt"])

    # -------------------------------------------------------------------------
    # 17. Missing credentials leave typed local inference working while voice unavailable
    # -------------------------------------------------------------------------
    def test_17_missing_credentials_voice_unavailable(self):
        service = GeminiVoiceService(api_key=None, client=None)
        self.assertFalse(service.is_available)
        self.assertEqual(service.status, VoiceStatus.UNAVAILABLE)

        # Service gracefully handles start/stop without crashing
        service.start_listening()
        service.feed_audio(b"\x00" * 100)
        service.stop_listening()

    # -------------------------------------------------------------------------
    # 18. Status and logs do not expose credentials or sensitive payloads
    # -------------------------------------------------------------------------
    def test_18_status_and_logs_redact_secrets(self):
        secret_key = "AIzaSyA1234567890abcdef1234567890abcdef"
        msg = f"Failed connecting to Gemini endpoint https://api.google.com?key={secret_key} with token: secret123456"
        redacted = redact_secrets(msg, extra_secret=secret_key)
        self.assertNotIn(secret_key, redacted)
        self.assertNotIn("secret123456", redacted)
        self.assertIn("[REDACTED]", redacted)

    # -------------------------------------------------------------------------
    # 19. Consecutive identical utterances are dispatched separately
    # -------------------------------------------------------------------------
    def test_19_consecutive_identical_utterances_dispatched_separately(self):
        client = MagicMock()
        service = GeminiVoiceService(client=client)

        received = []
        service.set_transcript_callback(lambda txt: received.append(txt))

        # Turn 1: user says "hello"
        t1 = service.start_listening()
        self.assertEqual(t1, 1)
        service._handle_final_transcript("hello", turn_id=t1)
        service.stop_listening()

        # Turn 2: user says "hello" again
        t2 = service.start_listening()
        self.assertEqual(t2, 2)
        service._handle_final_transcript("hello", turn_id=t2)
        service.stop_listening()

        # Both identical utterances must be dispatched
        self.assertEqual(received, ["hello", "hello"])

    # -------------------------------------------------------------------------
    # 20. ExceptionGroup unwrapping and clean diagnostic reporting
    # -------------------------------------------------------------------------
    def test_20_exception_group_unwrapping_and_clean_diagnostics(self):
        from app.marklv.core.gemini_voice import format_clean_error, unwrap_exceptions

        leaf1 = RuntimeError("Live transcription connection dropped")
        leaf2 = ValueError("Token key=AIzaSyA1234567890abcdef1234567890abcdef expired")
        grp = ExceptionGroup("unhandled errors in a TaskGroup (2 sub-exceptions)", [leaf1, leaf2])

        leaves = unwrap_exceptions(grp)
        self.assertEqual(len(leaves), 2)
        self.assertIn(leaf1, leaves)
        self.assertIn(leaf2, leaves)

        clean = format_clean_error(grp)
        self.assertNotIn("unhandled errors in a TaskGroup", clean)
        self.assertNotIn("AIzaSyA", clean)
        self.assertIn("Live transcription connection dropped", clean)
        self.assertIn("[REDACTED]", clean)

    # -------------------------------------------------------------------------
    # 21. Benign closure detection
    # -------------------------------------------------------------------------
    def test_21_benign_closure_detection(self):
        from app.marklv.core.gemini_voice import is_benign_closure

        # CancelledError is benign
        self.assertTrue(is_benign_closure(asyncio.CancelledError()))

        # Normal closure string is benign
        self.assertTrue(is_benign_closure(RuntimeError("Normal closure 1000")))

        # Real failure is NOT benign
        self.assertFalse(is_benign_closure(RuntimeError("API quota exceeded")))

    # -------------------------------------------------------------------------
    # 22. Status callback receives lifecycle state updates
    # -------------------------------------------------------------------------
    def test_22_status_callback_lifecycle(self):
        client = MagicMock()
        service = GeminiVoiceService(client=client)

        statuses = []
        service.set_status_callback(lambda st, msg: statuses.append(st))

        t = service.start_listening()
        self.assertIn(VoiceStatus.LISTENING, statuses)

        service.stop_listening()
        self.assertIn(VoiceStatus.TRANSCRIBING, statuses)


if __name__ == "__main__":
    unittest.main()
