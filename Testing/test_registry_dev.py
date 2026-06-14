import shutil
from pathlib import Path
from app.nodes.loop import execute_single_tool

def test_1_create_project():
    print("\n--- TEST 1: Create Project (Scaffolder) ---")
    res = execute_single_tool(
        tool_name="project_scaffolder",
        args={
            "description": "A Python CLI calculator that adds numbers.",
            "output_dir": "test_registry_dir/calculator"
        }
    )
    print("Scaffolder Result:", res["success"])
    assert res["success"]
    assert "calculator" in res["result"]

def test_2_modify_file():
    print("\n--- TEST 2: Modify File (Code Helper) ---")
    mock_file = Path("test_registry_dir/calculator/main.py")
    if not mock_file.exists():
        mock_file.parent.mkdir(parents=True, exist_ok=True)
        mock_file.write_text("print('Hello')", encoding="utf-8")

    res = execute_single_tool(
        tool_name="code_helper",
        args={
            "action": "edit",
            "file_path": str(mock_file),
            "description": "Change the print statement to print 'Goodbye'"
        }
    )
    print("CodeHelper Result:", res["success"])
    assert res["success"]
    assert "File edited" in res["result"]

def test_3_analyze_traceback():
    print("\n--- TEST 3: Analyze Traceback (Code Analyzer) ---")
    traceback = """Traceback (most recent call last):
  File "main.py", line 2, in <module>
    import missing_library
ModuleNotFoundError: No module named 'missing_library'"""

    res = execute_single_tool(
        tool_name="code_helper",
        args={
            "action": "debug",
            "description": traceback,
            "file_path": "test_registry_dir/calculator/main.py"
        }
    )
    print("CodeAnalyzer Result:", res["success"])
    assert res["success"]
    assert "missing" in res["result"]
    assert "Diagnostic" in res["result"]
    print(res["result"])

if __name__ == "__main__":
    base_dir = Path("test_registry_dir")
    try:
        test_1_create_project()
        test_2_modify_file()
        test_3_analyze_traceback()
        print("\nAll registry tests passed successfully!")
    finally:
        if base_dir.exists():
            shutil.rmtree(base_dir)
