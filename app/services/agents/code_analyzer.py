import re
from pathlib import Path
from typing import Optional, Tuple

class CodeAnalyzer:
    """
    Handles text-based code analysis, traceback parsing, error classification,
    and intent detection for the Dev Agent.
    """

    @staticmethod
    def classify_error(output: str) -> str:
        """Classifies the type of python error from output."""
        low = output.lower()

        if any(x in low for x in ("no module named", "modulenotfounderror", "importerror")):
            return "dependency_error"

        if "syntaxerror" in low or "invalid syntax" in low:
            return "syntax_error"
        
        if "cannot import" in low or "importerror" in low:
            return "import_error"

        if any(x in low for x in (
            "traceback", "exception", "error:", "nameerror", "typeerror",
            "attributeerror", "valueerror", "keyerror", "indexerror",
            "zerodivisionerror", "filenotfounderror", "permissionerror",
        )):
            return "runtime_error"

        return "none"

    @staticmethod
    def has_error(output: str) -> bool:
        """Determines if the output contains an error."""
        low = output.lower()

        if "timed out" in low:
            return False

        if not output.strip():
            return False

        error_type = CodeAnalyzer.classify_error(output)
        if error_type != "none":
            return True
            
        # Fallback signals from code_helper
        error_signals = ["failed", "crash", "stderr"]
        return any(s in low for s in error_signals)

    @staticmethod
    def parse_traceback(output: str, project_files: list[str]) -> Tuple[Optional[str], Optional[int]]:
        """Extracts the exact file and line number where the error occurred."""
        pattern = re.compile(r'File ["\']([^"\']+\.py)["\'],\s+line\s+(\d+)', re.IGNORECASE)
        matches = pattern.findall(output)

        for raw_path, line_str in reversed(matches):
            raw_name = Path(raw_path).name
            for pf in project_files:
                if Path(pf).name == raw_name or pf == raw_path or raw_path.endswith(pf):
                    return pf, int(line_str)

        return None, None

    @staticmethod
    def extract_missing_module(error_output: str) -> Optional[str]:
        """Extracts the missing module name from a ModuleNotFoundError."""
        pattern = re.compile(
            r"No module named ['\"]([a-zA-Z0-9_\-\.]+)['\"]", re.IGNORECASE
        )
        match = pattern.search(error_output)
        if not match:
            return None

        # Clean up the package name
        pkg = match.group(1).replace("_", "-").split(".")[0]
        return pkg

    @staticmethod
    def detect_intent(description: str, file_path: str, code: str) -> str:
        """Detects the intended code_helper action from natural language."""
        desc = (description or "").lower()

        screen_kw = ["ekrandaki", "screen", "ekranda", "bu hatayı", "why am i getting",
                     "neden hata", "what's wrong", "ne yanlış", "screenshot", "görüntü"]
        if any(k in desc for k in screen_kw):
            return "screen_debug"

        # Optimize keywords
        optimize_kw = ["optimize", "refactor", "clean up", "improve", "temizle",
                       "iyileştir", "daha iyi", "make it better", "hızlandır"]
        if any(k in desc for k in optimize_kw) and (code or file_path):
            return "optimize"

        if file_path:
            p = Path(file_path)
            edit_kw  = ["edit", "update", "modify", "change", "add", "remove",
                        "refactor", "fix", "rename", "replace", "düzenle", "değiştir"]
            run_kw   = ["run", "execute", "launch", "start", "çalıştır"]
            build_kw = ["build", "make it work", "try", "attempt"]

            if p.exists() and any(k in desc for k in edit_kw):
                return "edit"
            if p.exists() and any(k in desc for k in run_kw):
                return "run"
            if any(k in desc for k in build_kw):
                return "build"
            if p.exists():
                return "explain"

        explain_kw = ["explain", "what does", "describe", "analyze", "açıkla", "ne yapıyor"]
        if any(k in desc for k in explain_kw) and (code or file_path):
            return "explain"

        build_kw = ["build", "make it work", "try and", "attempt"]
        if any(k in desc for k in build_kw):
            return "build"

        return "write"
