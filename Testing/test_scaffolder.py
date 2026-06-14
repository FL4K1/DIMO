import shutil
from pathlib import Path
from app.services.agents.project_scaffolder import ProjectScaffolder

def logger(msg):
    print(msg)

def test_python_cli_project():
    print("Testing Python CLI Project Planning...")
    plan = ProjectScaffolder.plan_project("A simple python CLI tool to reverse a string", logger=logger)
    
    assert "project_name" in plan
    assert "files" in plan
    
    print(f"CLI Plan generated: {plan['project_name']} with {len(plan['files'])} files.")
    
    # Generate struct
    base_dir = Path("test_projects_dir")
    proj_dir = ProjectScaffolder.generate_project_structure(plan, base_dir, logger=logger)
    
    assert proj_dir.exists()
    assert proj_dir.is_dir()
    
    readme = ProjectScaffolder.generate_readme(plan, proj_dir, "A simple CLI tool")
    assert readme.exists()
    
    print("CLI Structure tests passed.")
    return proj_dir

def test_flask_api_project():
    print("\nTesting Flask API Project Planning...")
    plan = ProjectScaffolder.plan_project("A small Flask API that returns Hello World on the / route", logger=logger)
    
    assert "project_name" in plan
    assert "files" in plan
    
    deps = ProjectScaffolder.build_dependency_map(plan)
    assert any("flask" in d.lower() for d in deps), "Flask dependency should be in the plan"
    
    print(f"Flask API Plan generated: {plan['project_name']} with {len(plan['files'])} files.")
    print("Flask Plan passed.")

if __name__ == "__main__":
    try:
        cli_dir = test_python_cli_project()
        test_flask_api_project()
        print("\nAll ProjectScaffolder tests passed.")
    finally:
        # Cleanup
        base_dir = Path("test_projects_dir")
        if base_dir.exists():
            shutil.rmtree(base_dir)
