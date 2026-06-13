import re
from pathlib import Path
from app.services.agents.llm_gateway import LLMGateway
from app.services.agents.prompts import code_prompts

class CodeHelper:
    """
    Handles LLM-driven code generation, editing, and explanation.
    Does not execute code or take screenshots.
    """

    @staticmethod
    def _clean_code(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        return text.strip()

    @staticmethod
    def _read_file(file_path: str) -> tuple[str, str]:
        if not file_path:
            return "", "No file path provided."
        p = Path(file_path)
        if not p.exists():
            return "", f"File not found: {file_path}"
        try:
            return p.read_text(encoding="utf-8"), ""
        except Exception as e:
            return "", f"Could not read file: {e}"

    @staticmethod
    def _save_file(path: Path, content: str) -> str:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"Saved to: {path}"
        except Exception as e:
            return f"Could not save: {e}"

    @staticmethod
    def _resolve_save_path(output_path: str, language: str) -> Path:
        ext_map = {
            "python": ".py", "py": ".py",
            "javascript": ".js", "js": ".js",
            "typescript": ".ts", "ts": ".ts",
            "html": ".html", "css": ".css",
            "java": ".java", "cpp": ".cpp", "c": ".c",
            "bash": ".sh", "shell": ".sh", "powershell": ".ps1",
            "sql": ".sql", "json": ".json", "rust": ".rs", "go": ".go",
        }
        desktop = Path.home() / "Desktop"
        if output_path:
            p = Path(output_path)
            return p if p.is_absolute() else desktop / p
        ext = ext_map.get((language or "python").lower(), ".py")
        return desktop / f"jarvis_code{ext}"

    @staticmethod
    def _preview(code: str, lines: int = 10) -> str:
        all_lines = code.splitlines()
        preview   = "\n".join(all_lines[:lines])
        suffix    = f"\n... ({len(all_lines) - lines} more lines)" if len(all_lines) > lines else ""
        return preview + suffix

    @staticmethod
    def write_file_from_prompt(description: str, language: str = "python", output_path: str = "", logger=None) -> str:
        if not description:
            return "Please describe what you want me to write."
        if logger:
            logger("[CodeHelper] Generating code...")

        lang = language or "python"
        prompt = code_prompts.CODE_WRITE_PROMPT.format(language=lang, description=description)
        
        response = LLMGateway.generate(prompt)
        if response.startswith("Error:"):
            return response

        code = CodeHelper._clean_code(response)
        path = CodeHelper._resolve_save_path(output_path, lang)
        
        status = CodeHelper._save_file(path, code)
        if logger:
            logger(f"[CodeHelper] Written: {path.name}")
        
        return f"Code written. {status}\n\nPreview:\n{CodeHelper._preview(code)}"

    @staticmethod
    def edit_existing_file(file_path: str, instruction: str, logger=None) -> str:
        if not file_path:
            return "Please provide a file path to edit."
        if not instruction:
            return "Please describe what change to make."

        content, err = CodeHelper._read_file(file_path)
        if err:
            return err

        if logger:
            logger("[CodeHelper] Editing file...")

        prompt = code_prompts.CODE_EDIT_PROMPT.format(instruction=instruction, content=content)
        
        response = LLMGateway.generate(prompt)
        if response.startswith("Error:"):
            return response

        edited = CodeHelper._clean_code(response)
        status = CodeHelper._save_file(Path(file_path), edited)
        
        if logger:
            logger(f"[CodeHelper] Edited: {Path(file_path).name}")
            
        return f"File edited. {status}\n\nPreview:\n{CodeHelper._preview(edited)}"

    @staticmethod
    def explain_code(file_path: str = "", code: str = "", logger=None) -> str:
        if file_path and not code:
            code, err = CodeHelper._read_file(file_path)
            if err:
                return err
        if not code:
            return "Please provide code or a file path to explain."

        if logger:
            logger("[CodeHelper] Analyzing code...")

        prompt = code_prompts.CODE_EXPLAIN_PROMPT.format(code=code[:4000])
        response = LLMGateway.generate(prompt)
        return response

    @staticmethod
    def optimize_code(file_path: str = "", code: str = "", language: str = "python", output_path: str = "", logger=None) -> str:
        if file_path and not code:
            code, err = CodeHelper._read_file(file_path)
            if err:
                return err
        if not code:
            return "Please provide code or a file path to optimize."

        if logger:
            logger("[CodeHelper] Optimizing code...")

        lang = language or "python"
        prompt = code_prompts.CODE_OPTIMIZE_PROMPT.format(language=lang, code=code[:6000])
        
        response = LLMGateway.generate(prompt)
        if response.startswith("Error:"):
            return response

        optimized = CodeHelper._clean_code(response)

        if file_path:
            save_path = Path(file_path)
        else:
            save_path = CodeHelper._resolve_save_path(output_path, lang)

        status = CodeHelper._save_file(save_path, optimized)
        
        if logger:
            logger(f"[CodeHelper] Optimized: {save_path.name}")

        original_lines = len(code.splitlines())
        optimized_lines = len(optimized.splitlines())
        diff = original_lines - optimized_lines

        return (
            f"Code optimized. {status}\n"
            f"Lines: {original_lines} -> {optimized_lines} "
            f"({'-' if diff > 0 else '+'}{abs(diff)} lines)\n\n"
            f"Preview:\n{CodeHelper._preview(optimized)}"
        )

    @staticmethod
    def refactor_code(code: str, error_output: str, description: str) -> str:
        """Internal bug-fixing logic, returns raw code."""
        prompt = code_prompts.CODE_FIX_PROMPT.format(
            description=description,
            error_output=error_output[:2000],
            code=code
        )
        response = LLMGateway.generate(prompt)
        return CodeHelper._clean_code(response)

    @staticmethod
    def generate_tests(file_path: str = "", code: str = "", language: str = "python", output_path: str = "", logger=None) -> str:
        if file_path and not code:
            code, err = CodeHelper._read_file(file_path)
            if err:
                return err
        if not code:
            return "Please provide code or a file path to generate tests for."

        if logger:
            logger("[CodeHelper] Generating tests...")

        lang = language or "python"
        prompt = code_prompts.CODE_TEST_GENERATE_PROMPT.format(language=lang, code=code[:6000])
        
        response = LLMGateway.generate(prompt)
        if response.startswith("Error:"):
            return response

        test_code = CodeHelper._clean_code(response)

        if output_path:
            save_path = CodeHelper._resolve_save_path(output_path, lang)
        elif file_path:
            orig = Path(file_path)
            save_path = orig.parent / f"test_{orig.name}"
        else:
            save_path = CodeHelper._resolve_save_path("test_jarvis_code", lang)

        status = CodeHelper._save_file(save_path, test_code)
        
        if logger:
            logger(f"[CodeHelper] Tests generated: {save_path.name}")

        return f"Tests generated. {status}\n\nPreview:\n{CodeHelper._preview(test_code)}"
