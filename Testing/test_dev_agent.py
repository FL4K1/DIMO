import shutil
from pathlib import Path
from app.services.agents.dev_agent import DevAgent

def logger(msg):
    print(msg)

def test_1_create_project():
    print("\n--- TEST 1: Create Project ---")
    base_dir = Path("test_dev_agent_dir")
    
    result = DevAgent.create_project(
        description="A Python CLI calculator that adds or subtracts two numbers",
        base_dir=base_dir,
        language="python",
        logger=logger
    )
    
    assert result["status"] == "success"
    assert "project_name" in result
    print(f"Project created at: {result['project_dir']}")
    print(f"Files generated: {len(result['files_generated'])}")
    
    return Path(result["project_dir"])

def test_2_modify_project():
    print("\n--- TEST 2: Modify Project ---")
    # Setup mock file
    file_path = Path("mock_calculator.py")
    file_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    
    result = DevAgent.modify_project(
        file_path=str(file_path),
        instruction="Add a subtract function to this file.",
        logger=logger
    )
    
    assert "File edited" in result
    print("Modify project successful.")
    
    file_path.unlink()

def test_3_analyze_traceback():
    print("\n--- TEST 3: Analyze Traceback ---")
    traceback = """Traceback (most recent call last):
  File "main.py", line 2, in <module>
    import requests
ModuleNotFoundError: No module named 'requests'"""
    
    result = DevAgent.debug_project(
        error_output=traceback,
        description="My script is crashing.",
        logger=logger
    )
    
    assert "requests" in result
    assert "Dependency error" in result
    print(f"Traceback diagnosis: {result}")

if __name__ == "__main__":
    base_dir = Path("test_dev_agent_dir")
    try:
        test_1_create_project()
        test_2_modify_project()
        test_3_analyze_traceback()
        print("\nAll DevAgent Orchestrator tests passed!")
    finally:
        if base_dir.exists():
            shutil.rmtree(base_dir)
