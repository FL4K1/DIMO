import json
import re
from pathlib import Path
from typing import Dict, Any, List

from app.services.agents.llm_gateway import LLMGateway
from app.services.agents.prompts import code_prompts

class ProjectScaffolder:
    """
    Handles JSON-based project planning and multi-file code generation.
    Does not handle execution, environment setup, or debugging.
    """

    @staticmethod
    def _clean_json(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```json\n?", "", text)
        text = re.sub(r"^```\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        return text.strip()

    @staticmethod
    def _clean_code(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        return text.strip()

    @staticmethod
    def plan_project(description: str, logger=None) -> Dict[str, Any]:
        """Generates a JSON plan for the project architecture."""
        if logger:
            logger("[Scaffolder] Generating project plan...")
            
        prompt = code_prompts.PROJECT_PLAN_PROMPT.format(description=description)
        response = LLMGateway.generate(prompt)
        
        if response.startswith("Error:"):
            raise RuntimeError(f"LLM Error during planning: {response}")
            
        clean_json = ProjectScaffolder._clean_json(response)
        
        try:
            plan = json.loads(clean_json)
            return plan
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM project plan as JSON: {e}\nResponse:\n{clean_json}")

    @staticmethod
    def generate_project_structure(plan: Dict[str, Any], base_path: Path, logger=None) -> Path:
        """Creates the directory structure for the project based on the plan."""
        project_name = plan.get("project_name", "generated_project").replace(" ", "_")
        project_dir = base_path / project_name
        
        # Create base dir
        project_dir.mkdir(parents=True, exist_ok=True)
        if logger:
            logger(f"[Scaffolder] Created project directory: {project_dir}")
            
        # Create nested directories for all files
        for file_info in plan.get("files", []):
            file_path = project_dir / file_info.get("path", "")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
        return project_dir

    @staticmethod
    def generate_project_files(plan: Dict[str, Any], project_dir: Path, language: str = "python", logger=None) -> List[Path]:
        """Iterates through the plan and generates code for each file using the LLM."""
        generated_paths = []
        files = plan.get("files", [])
        
        # Create a compressed string version of the plan for context
        plan_context = json.dumps(
            {
                "project_name": plan.get("project_name"),
                "files": [{"path": f["path"], "description": f["description"]} for f in files]
            }, 
            indent=2
        )
        
        for file_info in files:
            rel_path = file_info.get("path")
            desc = file_info.get("description")
            
            if logger:
                logger(f"[Scaffolder] Generating file: {rel_path}")
                
            prompt = code_prompts.PROJECT_FILE_PROMPT.format(
                language=language,
                project_plan=plan_context,
                file_path=rel_path,
                file_description=desc
            )
            
            response = LLMGateway.generate(prompt)
            if response.startswith("Error:"):
                if logger:
                    logger(f"[Scaffolder] Error generating {rel_path}: {response}")
                continue
                
            code = ProjectScaffolder._clean_code(response)
            file_path = project_dir / rel_path
            
            # Save file
            file_path.write_text(code, encoding="utf-8")
            generated_paths.append(file_path)
            
        return generated_paths

    @staticmethod
    def build_dependency_map(plan: Dict[str, Any]) -> List[str]:
        """Extracts and sanitizes the dependencies from the plan."""
        deps = plan.get("dependencies", [])
        if not isinstance(deps, list):
            return []
        
        cleaned = []
        for d in deps:
            d = str(d).strip()
            if d and not d.startswith("#"):
                cleaned.append(d)
        return cleaned

    @staticmethod
    def generate_readme(plan: Dict[str, Any], project_dir: Path, description: str) -> Path:
        """Generates a standard README.md for the project."""
        readme_path = project_dir / "README.md"
        
        lines = [
            f"# {plan.get('project_name', 'Generated Project')}",
            "",
            f"**Description:** {description}",
            "",
            "## Architecture",
            "This project was generated with the following file structure:",
            ""
        ]
        
        for f in plan.get("files", []):
            lines.append(f"- `{f.get('path')}`: {f.get('description')}")
            
        lines.extend([
            "",
            "## Dependencies",
            "```text"
        ])
        for d in ProjectScaffolder.build_dependency_map(plan):
            lines.append(d)
        lines.extend([
            "```",
            "",
            "## Running",
            "Ensure you have installed the dependencies, then run the entry point file."
        ])
        
        readme_path.write_text("\n".join(lines), encoding="utf-8")
        return readme_path
