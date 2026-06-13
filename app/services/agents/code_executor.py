import subprocess
import sys
import re
import time
from pathlib import Path
from typing import Optional


class CodeExecutor:
    """
    Handles all isolated system-level execution for the Dev Agent:
    - Running files and projects
    - Installing dependencies via pip
    - Opening VSCode
    """

    @staticmethod
    def install_dependencies(dependencies: list[str], project_dir: Path, logger=None) -> str:
        if not dependencies:
            return "No external dependencies."

        def log(msg):
            if logger:
                logger(f"[Executor] {msg}")

        to_install = []
        for dep in dependencies:
            pkg_name = re.split(r"[>=<!]", dep)[0].strip()
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", pkg_name],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                to_install.append(dep)
            else:
                log(f"✓ Already installed: {pkg_name}")

        if not to_install:
            return f"All dependencies already installed: {', '.join(dependencies)}"

        log(f"Installing: {to_install}")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install"] + to_install,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=120, cwd=str(project_dir)
            )
            if result.returncode == 0:
                return f"Installed: {', '.join(to_install)}"
            return f"Install warning (non-fatal): {result.stderr[:200]}"
        except subprocess.TimeoutExpired:
            return "Dependency install timed out (non-fatal)."
        except Exception as e:
            return f"Install error (non-fatal): {e}"

    @staticmethod
    def try_auto_install(error_output: str, project_dir: Path, logger=None) -> bool:
        """Attempts to auto-install missing packages found in ModuleNotFoundError."""
        pattern = re.compile(
            r"No module named ['\"]([a-zA-Z0-9_\-\.]+)['\"]", re.IGNORECASE
        )
        match = pattern.search(error_output)
        if not match:
            return False

        pkg = match.group(1).replace("_", "-").split(".")[0]
        if logger:
            logger(f"[Executor] Auto-installing missing package: {pkg}")

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=60, cwd=str(project_dir)
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def open_vscode(project_dir: Path, logger=None) -> bool:
        vscode_candidates = [
            "code",
            rf"C:\Users\{Path.home().name}\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd",
            r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
        ]
        for cmd in vscode_candidates:
            try:
                subprocess.Popen(
                    [cmd, str(project_dir)],
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                time.sleep(1.5)
                if logger:
                    logger(f"[Executor] VSCode opened: {project_dir}")
                return True
            except Exception:
                continue
        return False

    @staticmethod
    def run_project(run_command: str, project_dir: Path, timeout: int = 30, logger=None) -> str:
        if logger:
            logger(f"[Executor] Running: {run_command}")
        try:
            parts = run_command.split()
            if parts[0].lower() == "python":
                parts[0] = sys.executable

            result = subprocess.run(
                parts,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=timeout,
                cwd=str(project_dir)
            )

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            combined_parts = []
            if stdout:
                combined_parts.append(f"STDOUT:\n{stdout}")
            if stderr:
                combined_parts.append(f"STDERR:\n{stderr}")

            return "\n\n".join(combined_parts) if combined_parts else "Ran with no output."

        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s — long-running app (server/GUI) is likely working."
        except FileNotFoundError as e:
            return f"Command not found: {e}"
        except Exception as e:
            return f"Run error: {e}"

    @staticmethod
    def run_file(path: Path, args: Optional[list] = None, timeout: int = 30, logger=None) -> str:
        interpreters = {
            ".py":  [sys.executable],
            ".js":  ["node"],
            ".ts":  ["ts-node"],
            ".sh":  ["bash"],
            ".ps1": ["powershell", "-File"],
            ".rb":  ["ruby"],
            ".php": ["php"],
        }
        interp = interpreters.get(path.suffix.lower())
        if not interp:
            return f"No interpreter for {path.suffix}."

        if logger:
            logger(f"[Executor] Running file: {path.name}")

        try:
            result = subprocess.run(
                interp + [str(path)] + (args or []),
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=timeout, cwd=str(path.parent)
            )
            output = result.stdout.strip()
            error  = result.stderr.strip()
            parts  = []
            if output: parts.append(f"Output:\n{output}")
            if error:  parts.append(f"Stderr:\n{error}")
            return "\n\n".join(parts) if parts else "Executed with no output."

        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s."
        except FileNotFoundError:
            return f"Interpreter not found: {interp[0]}."
        except Exception as e:
            return f"Execution error: {e}"
