"""
Ollama Manager for Mark-LV.

Authoritative readiness and lifecycle manager for local Ollama instances.
Tracks process ownership, serializes launches, verifies exact model availability,
and validates live bounded inference before reporting readiness.

Injectable HTTP client and process launcher enable deterministic unit testing
without live Ollama or models installed.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import urlparse

logger = logging.getLogger("marklv.ollama_manager")


class OllamaReadinessStatus(str, Enum):
    READY = "ready"
    SERVER_UNREACHABLE = "server_unreachable"
    LAUNCH_FAILED = "launch_failed"
    MODEL_MISSING = "model_missing"
    INFERENCE_FAILED = "inference_failed"
    TIMEOUT = "timeout"
    CONFIGURATION_MISMATCH = "configuration_mismatch"


class ProcessOwnership(str, Enum):
    EXTERNAL = "external"
    MANAGED = "managed"
    NONE = "none"


@dataclass
class OllamaReadinessResult:
    status: OllamaReadinessStatus
    stage: str
    message: str
    endpoint: str
    model: str
    process_ownership: ProcessOwnership = ProcessOwnership.NONE
    pid: Optional[int] = None

    @property
    def is_ready(self) -> bool:
        return self.status == OllamaReadinessStatus.READY

    @property
    def is_managed(self) -> bool:
        return self.process_ownership == ProcessOwnership.MANAGED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "stage": self.stage,
            "message": self.message,
            "endpoint": self.endpoint,
            "model": self.model,
            "process_ownership": self.process_ownership.value,
            "pid": self.pid,
            "is_ready": self.is_ready,
            "is_managed": self.is_managed,
        }


class HttpClientProtocol(Protocol):
    def get(self, url: str, timeout: Any = 5.0) -> Any: ...
    def post(self, url: str, json: Optional[dict] = None, timeout: Any = 10.0) -> Any: ...


class ProcessLauncherProtocol(Protocol):
    def find_executable(self, name: str = "ollama") -> Optional[str]: ...
    def launch(self, command: List[str]) -> Any: ...


class DefaultHttpClient:
    """Standard HTTP client using the requests library."""

    def get(self, url: str, timeout: Any = 5.0) -> Any:
        import requests
        return requests.get(url, timeout=timeout)

    def post(self, url: str, json: Optional[dict] = None, timeout: Any = 10.0) -> Any:
        import requests
        return requests.post(url, json=json, timeout=timeout)


class DefaultProcessLauncher:
    """Standard process launcher with Windows installation path discovery."""

    def find_executable(self, name: str = "ollama") -> Optional[str]:
        # 1. Standard PATH resolution
        found = shutil.which(name)
        if found:
            return found

        # 2. Windows-specific user and system candidate locations
        if sys.platform == "win32":
            candidates: List[str] = []
            local_app = os.environ.get("LOCALAPPDATA")
            if local_app:
                candidates.append(os.path.join(local_app, "Programs", "Ollama", "ollama.exe"))

            prog_files = os.environ.get("PROGRAMFILES")
            if prog_files:
                candidates.append(os.path.join(prog_files, "Ollama", "ollama.exe"))

            prog_files_x86 = os.environ.get("PROGRAMFILES(X86)")
            if prog_files_x86:
                candidates.append(os.path.join(prog_files_x86, "Ollama", "ollama.exe"))

            user_profile = os.environ.get("USERPROFILE")
            if user_profile:
                candidates.append(os.path.join(user_profile, "AppData", "Local", "Programs", "Ollama", "ollama.exe"))

            for path in candidates:
                if os.path.isfile(path) and os.access(path, os.X_OK):
                    return path

        return None

    def launch(self, command: List[str]) -> subprocess.Popen:
        kwargs: Dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(command, **kwargs)


def sanitize_message(msg: str) -> str:
    """Sanitize error messages and endpoints to avoid leaking tokens, passwords, or credentials."""
    if not isinstance(msg, str):
        msg = str(msg)
    # Mask credentials embedded in URLs: https?://user:pass@host (handles passwords with @ or special chars)
    msg = re.sub(r'(https?://)[^/\s]+@', r'\1***:***@', msg)
    # Mask common key and token patterns
    msg = re.sub(r'(?:key|token|secret|password|api[_-]?key)=[\w\-.]+', 'token=***', msg, flags=re.IGNORECASE)
    msg = re.sub(r'Bearer\s+[\w\-.]+', 'Bearer ***', msg, flags=re.IGNORECASE)
    return msg


def is_model_installed(configured_model: str, installed_models: List[str]) -> bool:
    """
    Verify whether the configured model matches any installed model tag.

    Strict matching rules:
    - If configured specifies a tag (e.g. 'llama3:8b'), it must match that exact tag.
      It will NOT match 'llama3:latest' or 'llama3.2:8b'.
    - If configured does not specify a tag (e.g. 'llama3.2'), it matches 'llama3.2'
      or 'llama3.2:latest'. It will NOT match 'llama3.2:3b' or 'llama3'.
    - Disallows prefix false positives ('llama3' matching 'llama3.2' or 'llama3-gradient').
    """
    target = configured_model.strip()
    if not target:
        return False

    def clean_name(n: str) -> str:
        # Strip registry prefix if present (e.g., 'registry.ollama.ai/library/llama3.2:latest' -> 'llama3.2:latest')
        if "/" in n:
            n = n.split("/")[-1]
        return n.strip().lower()

    target_clean = clean_name(target)
    cleaned_installed = [clean_name(m) for m in installed_models if m]

    if ":" in target_clean:
        # Explicit tag required
        return target_clean in cleaned_installed
    else:
        # Untagged: in Ollama convention, untagged models default to ':latest'
        accepted = {target_clean, f"{target_clean}:latest"}
        return any(inst in accepted for inst in cleaned_installed)


class OllamaManager:
    """
    Manages Ollama server lifecycle and performs comprehensive readiness verification.

    Never starts duplicate servers, respects externally running servers,
    and requires real inference verification before declaring readiness.
    """

    DEFAULT_STARTUP_TIMEOUT: float = 15.0
    DEFAULT_REQUEST_TIMEOUT: float = 5.0
    DEFAULT_INFERENCE_TIMEOUT: float = 180.0
    DEFAULT_CONNECT_TIMEOUT: float = 5.0

    def __init__(
        self,
        host: Optional[str] = None,
        model: Optional[str] = None,
        http_client: Optional[HttpClientProtocol] = None,
        process_launcher: Optional[ProcessLauncherProtocol] = None,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        inference_timeout: float = DEFAULT_INFERENCE_TIMEOUT,
        total_timeout: Optional[float] = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        poll_interval: float = 0.5,
        launch_command: Optional[Sequence[str]] = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self._host = (host or self._get_default_host()).rstrip("/")
        self._safe_endpoint = sanitize_message(self._host)
        self._model = (model or self._get_default_model()).strip()
        self._http = http_client or DefaultHttpClient()
        self._launcher = process_launcher or DefaultProcessLauncher()
        self._startup_timeout = float(startup_timeout)
        self._request_timeout = float(request_timeout)
        self._inference_timeout = float(inference_timeout)
        self._connect_timeout = float(connect_timeout)
        self._total_timeout = (
            float(total_timeout)
            if total_timeout is not None
            else float(self._startup_timeout + self._request_timeout + self._inference_timeout)
        )
        self._poll_interval = float(poll_interval)
        self._launch_command = tuple(launch_command) if launch_command else None
        self._clock = clock
        self._sleeper = sleeper

        self._managed_process: Optional[Any] = None
        self._managed_pid: Optional[int] = None
        self._launch_lock = threading.Lock()
        self._last_result: Optional[OllamaReadinessResult] = None

    @staticmethod
    def _get_default_host() -> str:
        try:
            from app.marklv.core.llm_client import get_llm_settings
            url, _ = get_llm_settings()
            if url:
                return url
        except Exception:
            pass
        return os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    @staticmethod
    def _get_default_model() -> str:
        try:
            from app.marklv.core.llm_client import get_llm_settings
            _, model = get_llm_settings()
            if model:
                return model
        except Exception:
            pass
        return os.environ.get("LLM_MODEL", "qwen2.5:7b")

    @property
    def host(self) -> str:
        return self._host

    @property
    def model(self) -> str:
        return self._model

    @property
    def startup_timeout(self) -> float:
        return self._startup_timeout

    @property
    def request_timeout(self) -> float:
        return self._request_timeout

    @property
    def inference_timeout(self) -> float:
        return self._inference_timeout

    @property
    def connect_timeout(self) -> float:
        return self._connect_timeout

    @property
    def total_timeout(self) -> float:
        return self._total_timeout

    @property
    def is_managed(self) -> bool:
        return self._managed_process is not None and self._is_managed_process_alive()

    @property
    def managed_pid(self) -> Optional[int]:
        if self.is_managed:
            return self._managed_pid
        return None

    def _is_managed_process_alive(self) -> bool:
        if self._managed_process is None:
            return False
        if hasattr(self._managed_process, "poll"):
            return self._managed_process.poll() is None
        return True

    def _discard_exited_managed_process(self) -> bool:
        """Clear only a tracked child that has exited; never inspect external processes."""
        if self._managed_process is not None and not self._is_managed_process_alive():
            self._managed_process = None
            self._managed_pid = None
            return True
        return False

    def _is_local_endpoint(self) -> bool:
        """Return whether the configured endpoint is a loopback HTTP endpoint."""
        try:
            hostname = (urlparse(self._host).hostname or "").lower()
        except ValueError:
            return False
        return hostname in {"localhost", "127.0.0.1", "::1"}

    @staticmethod
    def _timeout_result(
        stage: str,
        endpoint: str,
        model: str,
        ownership: ProcessOwnership,
        pid: Optional[int],
    ) -> OllamaReadinessResult:
        return OllamaReadinessResult(
            status=OllamaReadinessStatus.TIMEOUT,
            stage=stage,
            message=f"Ollama readiness timed out during {stage}.",
            endpoint=endpoint,
            model=model,
            process_ownership=ownership,
            pid=pid,
        )

    def _remaining(self, deadline: float) -> float:
        return max(0.0, deadline - self._clock())

    def _request_timeout_for(self, deadline: float, cap: float) -> Optional[float]:
        remaining = self._remaining(deadline)
        return min(cap, remaining) if remaining > 0 else None

    def _ping_server(self, deadline: float) -> bool:
        """Lightweight reachability check to /api/tags."""
        request_timeout = self._request_timeout_for(deadline, self._request_timeout)
        if request_timeout is None:
            return False
        try:
            resp = self._http.get(f"{self._host}/api/tags", timeout=request_timeout)
            return getattr(resp, "status_code", 0) == 200
        except Exception:
            return False

    def _post_inference(
        self,
        url: str,
        payload: dict,
        connect_timeout: float,
        read_timeout: float,
    ) -> Any:
        """
        Execute inference POST with separate connect and read timeouts where supported.
        Falls back to read_timeout if HTTP client does not support tuple timeouts.
        """
        try:
            return self._http.post(url, json=payload, timeout=(connect_timeout, read_timeout))
        except TypeError:
            return self._http.post(url, json=payload, timeout=read_timeout)

    def check_readiness(
        self,
        auto_start: bool = True,
        override_model: Optional[str] = None,
        progress_callback: Optional[Callable[[str, str], None]] = None,
        total_timeout: Optional[float] = None,
    ) -> OllamaReadinessResult:
        """
        Execute full multi-stage readiness verification.

        Stages:
        1. Check server connectivity (bounded by request_timeout and total budget).
        2. Auto-start Ollama if unreachable and auto_start=True (bounded by startup_timeout).
        3. Query and verify exact configured model in installed tags (bounded by request_timeout).
        4. Validate real bounded inference on the model (bounded by inference_timeout with distinct connect/read timeouts).

        ``total_timeout`` governs the overall readiness budget across all stages.
        Each stage is bounded by its own specific timeout and cannot exceed the remaining overall budget.
        """
        def _report(stg: str, msg: str):
            if progress_callback:
                try:
                    progress_callback(stg, msg)
                except Exception:
                    pass

        model_name = (override_model or self._model).strip()
        budget = float(total_timeout) if total_timeout is not None else self._total_timeout
        deadline = self._clock() + budget
        self._discard_exited_managed_process()

        # ── Step 0: Verify that configured provider is Ollama ─────────────────
        try:
            from app.marklv.core.llm_client import get_llm_provider
            configured_provider = get_llm_provider()
            if configured_provider != "ollama":
                res = OllamaReadinessResult(
                    status=OllamaReadinessStatus.CONFIGURATION_MISMATCH,
                    stage="configuration_check",
                    message=(
                        f"Configured LLM provider in api_keys.json is '{configured_provider}'. "
                        "Local LLM Mode requires an Ollama provider."
                    ),
                    endpoint=self._safe_endpoint,
                    model=model_name,
                    process_ownership=ProcessOwnership.NONE,
                )
                self._last_result = res
                return res
        except Exception:
            pass

        # ── Step A: Check server connectivity ─────────────────────────────────
        _report("connectivity", f"Checking Ollama server connectivity at {self._safe_endpoint}...")
        server_up = self._ping_server(deadline)
        ownership = ProcessOwnership.NONE
        pid: Optional[int] = None

        if server_up:
            ownership = ProcessOwnership.MANAGED if self._is_managed_process_alive() else ProcessOwnership.EXTERNAL
            pid = self._managed_pid if ownership == ProcessOwnership.MANAGED else None
        else:
            # ── Step B: Start Ollama if necessary ──────────────────────────────
            if not auto_start:
                res = OllamaReadinessResult(
                    status=OllamaReadinessStatus.SERVER_UNREACHABLE,
                    stage="connectivity",
                    message=sanitize_message(f"Ollama server is unreachable at {self._safe_endpoint}."),
                    endpoint=self._safe_endpoint,
                    model=model_name,
                    process_ownership=ProcessOwnership.NONE,
                )
                self._last_result = res
                return res

            # Serialize concurrent launches to prevent race conditions / duplicate processes
            with self._launch_lock:
                # Recheck server connectivity under lock (another caller may have started it)
                self._discard_exited_managed_process()
                if self._ping_server(deadline):
                    ownership = ProcessOwnership.MANAGED if self._is_managed_process_alive() else ProcessOwnership.EXTERNAL
                    pid = self._managed_pid if ownership == ProcessOwnership.MANAGED else None
                else:
                    if self._remaining(deadline) <= 0:
                        res = self._timeout_result(
                            "launch", self._safe_endpoint, model_name, ProcessOwnership.NONE, None
                        )
                        self._last_result = res
                        return res

                    # A previous attempt may have timed out while its child was
                    # still starting. Reuse that child rather than spawning another.
                    if self._is_managed_process_alive():
                        proc = self._managed_process
                    else:
                        if not self._is_local_endpoint() and not self._launch_command:
                            res = OllamaReadinessResult(
                                status=OllamaReadinessStatus.SERVER_UNREACHABLE,
                                stage="launch",
                                message="Configured Ollama endpoint is remote; no launch command is configured.",
                                endpoint=self._safe_endpoint,
                                model=model_name,
                                process_ownership=ProcessOwnership.NONE,
                            )
                            self._last_result = res
                            return res

                        command = list(self._launch_command) if self._launch_command else None
                        if command is None:
                            exe = self._launcher.find_executable("ollama")
                            if not exe:
                                res = OllamaReadinessResult(
                                    status=OllamaReadinessStatus.LAUNCH_FAILED,
                                    stage="launch",
                                    message="Ollama executable not found in PATH or standard installation directories.",
                                    endpoint=self._safe_endpoint,
                                    model=model_name,
                                    process_ownership=ProcessOwnership.NONE,
                                )
                                self._last_result = res
                                return res
                            command = [exe, "serve"]

                        try:
                            proc = self._launcher.launch(command)
                            self._managed_process = proc
                            self._managed_pid = getattr(proc, "pid", None)
                        except Exception as e:
                            res = OllamaReadinessResult(
                                status=OllamaReadinessStatus.LAUNCH_FAILED,
                                stage="launch",
                                message=sanitize_message(f"Failed to launch Ollama executable: {e}"),
                                endpoint=self._safe_endpoint,
                                model=model_name,
                                process_ownership=ProcessOwnership.NONE,
                            )
                            self._last_result = res
                            return res

                    # Poll for server to become reachable within startup budget and total budget.
                    started = False
                    startup_budget = min(self._startup_timeout, self._remaining(deadline))
                    startup_deadline = self._clock() + startup_budget

                    while self._remaining(startup_deadline) > 0 and self._remaining(deadline) > 0:
                        if self._ping_server(min(startup_deadline, deadline)):
                            started = True
                            break
                        if not self._is_managed_process_alive():
                            self._discard_exited_managed_process()
                            break
                        rem_startup = self._remaining(startup_deadline)
                        rem_total = self._remaining(deadline)
                        self._sleeper(min(self._poll_interval, rem_startup, rem_total))

                    if not started:
                        ownership = ProcessOwnership.MANAGED if self._is_managed_process_alive() else ProcessOwnership.NONE
                        pid = self._managed_pid if ownership == ProcessOwnership.MANAGED else None
                        if self._remaining(deadline) <= 0:
                            res = self._timeout_result(
                                "launch", self._safe_endpoint, model_name, ownership, pid
                            )
                        else:
                            res = OllamaReadinessResult(
                                status=OllamaReadinessStatus.TIMEOUT,
                                stage="launch",
                                message=(
                                    f"Ollama server launched (PID {pid}) but failed to respond within "
                                    f"{self._startup_timeout}s."
                                    if ownership == ProcessOwnership.MANAGED
                                    else "Ollama server exited before becoming reachable."
                                ),
                                endpoint=self._safe_endpoint,
                                model=model_name,
                                process_ownership=ownership,
                                pid=pid,
                            )
                        self._last_result = res
                        return res

                    ownership = ProcessOwnership.MANAGED
                    pid = self._managed_pid

        # ── Step C: Verify configured model ───────────────────────────────────
        _report("model_check", f"Verifying model '{model_name}' availability...")
        request_timeout = self._request_timeout_for(deadline, self._request_timeout)
        if request_timeout is None:
            res = self._timeout_result("model_check", self._safe_endpoint, model_name, ownership, pid)
            self._last_result = res
            return res
        try:
            tags_resp = self._http.get(f"{self._host}/api/tags", timeout=request_timeout)
            if self._remaining(deadline) <= 0:
                res = self._timeout_result("model_check", self._safe_endpoint, model_name, ownership, pid)
                self._last_result = res
                return res
            status_code = getattr(tags_resp, "status_code", 0)
            if status_code != 200:
                res = OllamaReadinessResult(
                    status=OllamaReadinessStatus.SERVER_UNREACHABLE,
                    stage="model_check",
                    message=sanitize_message(f"Failed to query model list from {self._safe_endpoint} (HTTP {status_code})."),
                    endpoint=self._safe_endpoint,
                    model=model_name,
                    process_ownership=ownership,
                    pid=pid,
                )
                self._last_result = res
                return res

            tags_data = tags_resp.json() if hasattr(tags_resp, "json") else {}
        except Exception as e:
            is_timeout = "timeout" in type(e).__name__.lower() or "timeout" in str(e).lower()
            res = OllamaReadinessResult(
                status=OllamaReadinessStatus.TIMEOUT if is_timeout else OllamaReadinessStatus.SERVER_UNREACHABLE,
                stage="model_check",
                message=sanitize_message(f"Failed to query model tags from {self._safe_endpoint}: {e}"),
                endpoint=self._safe_endpoint,
                model=model_name,
                process_ownership=ownership,
                pid=pid,
            )
            self._last_result = res
            return res

        models_list = tags_data.get("models", []) if isinstance(tags_data, dict) else []
        installed_names: List[str] = []
        for item in models_list:
            if isinstance(item, dict):
                if "name" in item:
                    installed_names.append(str(item["name"]))
                if "model" in item and item["model"] != item.get("name"):
                    installed_names.append(str(item["model"]))
            elif isinstance(item, str):
                installed_names.append(item)

        if not is_model_installed(model_name, installed_names):
            avail_str = ", ".join(sorted(set(installed_names))) if installed_names else "none"
            res = OllamaReadinessResult(
                status=OllamaReadinessStatus.MODEL_MISSING,
                stage="model_check",
                message=f"Model '{model_name}' is not installed in Ollama. Available models: [{avail_str}].",
                endpoint=self._safe_endpoint,
                model=model_name,
                process_ownership=ownership,
                pid=pid,
            )
            self._last_result = res
            return res

        # ── Step D: Verify real bounded inference ─────────────────────────────
        _report("inference", f"Testing inference with model '{model_name}'...")
        remaining = self._remaining(deadline)
        if remaining <= 0:
            res = self._timeout_result("inference", self._safe_endpoint, model_name, ownership, pid)
            self._last_result = res
            return res

        read_timeout = min(self._inference_timeout, remaining)
        connect_timeout = min(self._connect_timeout, remaining)
        if read_timeout <= 0 or connect_timeout <= 0:
            res = self._timeout_result("inference", self._safe_endpoint, model_name, ownership, pid)
            self._last_result = res
            return res

        payload = {
            "model": model_name,
            "prompt": "ping",
            "stream": False,
            "options": {"num_predict": 5},
        }

        try:
            inf_resp = self._post_inference(
                f"{self._host}/api/generate",
                payload=payload,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
            )
            if self._remaining(deadline) <= 0:
                res = self._timeout_result("inference", self._safe_endpoint, model_name, ownership, pid)
                self._last_result = res
                return res
            inf_status = getattr(inf_resp, "status_code", 0)
            if inf_status != 200:
                res = OllamaReadinessResult(
                    status=OllamaReadinessStatus.INFERENCE_FAILED,
                    stage="inference",
                    message=f"Model inference test failed with HTTP {inf_status}.",
                    endpoint=self._safe_endpoint,
                    model=model_name,
                    process_ownership=ownership,
                    pid=pid,
                )
                self._last_result = res
                return res

            data = inf_resp.json() if hasattr(inf_resp, "json") else {}
            output_text = ""
            if isinstance(data, dict):
                output_text = data.get("response") or (
                    data.get("message", {}).get("content", "")
                    if isinstance(data.get("message"), dict)
                    else ""
                )

            if not output_text or not str(output_text).strip():
                res = OllamaReadinessResult(
                    status=OllamaReadinessStatus.INFERENCE_FAILED,
                    stage="inference",
                    message=f"Model '{model_name}' returned empty or invalid inference response.",
                    endpoint=self._safe_endpoint,
                    model=model_name,
                    process_ownership=ownership,
                    pid=pid,
                )
                self._last_result = res
                return res

        except Exception as e:
            is_timeout = "timeout" in type(e).__name__.lower() or "timeout" in str(e).lower()
            res = OllamaReadinessResult(
                status=OllamaReadinessStatus.TIMEOUT if is_timeout else OllamaReadinessStatus.INFERENCE_FAILED,
                stage="inference",
                message=sanitize_message(f"Inference request to model '{model_name}' failed: {e}"),
                endpoint=self._safe_endpoint,
                model=model_name,
                process_ownership=ownership,
                pid=pid,
            )
            self._last_result = res
            return res

        # ── All stages verified: Ready ────────────────────────────────────────
        _report("ready", f"Ollama server at {self._safe_endpoint} and model '{model_name}' are ready for inference.")
        res = OllamaReadinessResult(
            status=OllamaReadinessStatus.READY,
            stage="ready",
            message=f"Ollama server at {self._safe_endpoint} and model '{model_name}' are ready for inference.",
            endpoint=self._safe_endpoint,
            model=model_name,
            process_ownership=ownership,
            pid=pid,
        )
        self._last_result = res
        return res

    def verify_or_start(
        self,
        progress_callback: Optional[Callable[[str, str], None]] = None,
        override_model: Optional[str] = None,
        total_timeout: Optional[float] = None,
    ) -> OllamaReadinessResult:
        """
        Convenience wrapper to verify readiness or start the local server with progress reporting.
        """
        return self.check_readiness(
            auto_start=True,
            override_model=override_model,
            progress_callback=progress_callback,
            total_timeout=total_timeout,
        )
