from app.services.agents.code_helper import CodeHelper
from pathlib import Path

def test_code_helper():
    print("Testing write_file_from_prompt...")
    res = CodeHelper.write_file_from_prompt("Write a python script that prints 'Hello World'", "python", "hello_world.py")
    assert "Code written" in res, f"Unexpected result: {res}"
    print("Write file passed.")

    # Cleanup
    p = Path("hello_world.py")
    if not p.is_absolute():
        p = Path.home() / "Desktop" / "hello_world.py"
    if p.exists():
        p.unlink()

if __name__ == "__main__":
    test_code_helper()
    print("All CodeHelper tests passed.")
