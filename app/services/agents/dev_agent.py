import json
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.services.agents.code_executor import CodeExecutor
from app.services.agents.code_analyzer import CodeAnalyzer
from app.services.agents.code_helper import CodeHelper
from app.services.agents.project_scaffolder import ProjectScaffolder
from app.services.agents.vision_debugger import VisionDebugger

class DevAgent:
    """
    Orchestrator for all coding tasks. 
    Coordinates CodeExecutor, CodeAnalyzer, CodeHelper, ProjectScaffolder, and VisionDebugger.
    Does not contain direct LLM prompts or subprocess logic.
    """

    @staticmethod
    def create_project(description: str, base_dir: Path, language: str = "python", logger=None) -> Dict[str, Any]:
        """Plans a project, generates the code, and creates the folder structure."""
        if logger:
            logger(f"[DevAgent] Orchestrating creation of new {language} project...")

        # 1. Plan
        plan = ProjectScaffolder.plan_project(description, logger=logger)
        
        # 2. Scaffold structure
        project_dir = ProjectScaffolder.generate_project_structure(plan, base_dir, logger=logger)
        
        # 3. Write files
        generated_files = ProjectScaffolder.generate_project_files(plan, project_dir, language=language, logger=logger)
        
        # 4. Write README
        readme_path = ProjectScaffolder.generate_readme(plan, project_dir, description)
        
        # 5. Extract dependencies
        deps = ProjectScaffolder.build_dependency_map(plan)

        return {
            "status": "success",
            "project_name": plan.get("project_name"),
            "project_dir": str(project_dir),
            "files_generated": [str(p) for p in generated_files] + [str(readme_path)],
            "dependencies": deps
        }

    @staticmethod
    def modify_project(file_path: str, instruction: str, logger=None) -> str:
        """Edits an existing file via CodeHelper."""
        if logger:
            logger(f"[DevAgent] Orchestrating modification for {file_path}")
            
        result = CodeHelper.edit_existing_file(file_path, instruction, logger=logger)
        return result

    @staticmethod
    def debug_project(error_output: str, description: str, code: str = "", file_path: str = "", use_vision: bool = False, logger=None) -> str:
        """Analyzes an error and provides a fix or insight."""
        if logger:
            logger("[DevAgent] Orchestrating debugging...")

        # If vision is requested, route to VisionDebugger
        if use_vision:
            return VisionDebugger.debug_screen(description, file_path=file_path, file_content=code, logger=logger)

        # 1. Analyze the error
        error_type = CodeAnalyzer.classify_error(error_output)
        
        if error_type == "dependency_error":
            missing_mod = CodeAnalyzer.extract_missing_module(error_output)
            return f"Diagnostic: Dependency error. Missing module is likely '{missing_mod}'. Install it to proceed."
            
        if error_type == "syntax_error":
            return CodeHelper.refactor_code(code, error_output, description)

        # 2. General traceback or runtime error logic
        if not code and file_path:
            # Fallback to loading the file if only path is provided
            try:
                code = Path(file_path).read_text(encoding="utf-8")
            except Exception:
                pass

        if code:
            if logger:
                logger("[DevAgent] Using CodeHelper to generate a fix...")
            fixed_code = CodeHelper.refactor_code(code, error_output, description)
            return f"Diagnostic: {error_type}. Suggested Fix:\n{fixed_code}"
            
        return f"Diagnostic: {error_type}. Error trace:\n{error_output}"

    @staticmethod
    def generate_tests(file_path: str, language: str = "python", output_path: str = "", logger=None) -> str:
        """Generates unit tests for an existing file via CodeHelper."""
        if logger:
            logger(f"[DevAgent] Orchestrating test generation for {file_path}")
            
        result = CodeHelper.generate_tests(file_path=file_path, language=language, output_path=output_path, logger=logger)
        return result
