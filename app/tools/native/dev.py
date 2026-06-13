import os
from pathlib import Path
from app.services.agents.dev_agent import DevAgent
from app.services.agents.code_helper import CodeHelper
from app.services.agents.project_scaffolder import ProjectScaffolder
from app.config.logging import logger

def get_base_dir() -> Path:
    # Use desktop as default workspace if not set
    return Path.home() / "Desktop" / "DIMO_Projects"

def dev_agent(
    description: str,
    language: str = "python",
    project_name: str = "",
    timeout: int = 30,
) -> dict:
    """Build complete multi-file projects from scratch."""
    try:
        base_dir = get_base_dir()
        if project_name:
            base_dir = base_dir / project_name
            
        result = DevAgent.create_project(
            description=description,
            base_dir=base_dir,
            language=language,
            logger=logger.info
        )
        return {"success": True, "result": str(result), "error": None}
    except Exception as e:
        logger.error(f"[Native] dev_agent failed: {e}")
        return {"success": False, "result": "", "error": str(e)}

def code_helper(
    action: str = "auto",
    description: str = "",
    language: str = "python",
    output_path: str = "",
    file_path: str = "",
    code: str = "",
    args: str = "",
    timeout: int = 30,
) -> dict:
    """Write, edit, explain, run, or build code files."""
    try:
        if action in ["write", "auto"] and output_path and description:
            res = CodeHelper.write_file_from_prompt(description, language, output_path, logger=logger.info)
            return {"success": True, "result": res, "error": None}
            
        elif action in ["edit", "auto"] and file_path and description:
            res = CodeHelper.edit_existing_file(file_path, description, logger=logger.info)
            return {"success": True, "result": res, "error": None}
            
        elif action == "explain" and (file_path or code):
            if file_path and not code:
                code = Path(file_path).read_text(encoding="utf-8")
            res = CodeHelper.explain_code(code, logger=logger.info)
            return {"success": True, "result": res, "error": None}
            
        elif action == "debug" and (description or code):
            res = DevAgent.debug_project(
                error_output=description,  # We'll pass traceback as description
                description="Fix this error.",
                code=code,
                file_path=file_path,
                logger=logger.info
            )
            return {"success": True, "result": res, "error": None}
            
        else:
            return {"success": False, "result": "", "error": f"Action '{action}' not fully mapped or missing arguments"}
    except Exception as e:
        logger.error(f"[Native] code_helper failed: {e}")
        return {"success": False, "result": "", "error": str(e)}

def project_scaffolder(description: str, output_dir: str = "") -> dict:
    """Plan a project JSON and output the folder structure."""
    try:
        plan = ProjectScaffolder.plan_project(description, logger=logger.info)
        base = Path(output_dir) if output_dir else get_base_dir()
        proj_dir = ProjectScaffolder.generate_project_structure(plan, base, logger=logger.info)
        return {"success": True, "result": f"Project structure planned and generated at {proj_dir}:\n{plan}", "error": None}
    except Exception as e:
        logger.error(f"[Native] project_scaffolder failed: {e}")
        return {"success": False, "result": "", "error": str(e)}
