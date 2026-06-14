from app.services.agents.code_executor import CodeExecutor
from pathlib import Path

def _test_logger(msg):
    print(f"LOG: {msg}")

test_file = Path("executor_test.py")
test_file.write_text("print('Hello from executor test!')", encoding="utf-8")

try:
    print("--- Testing run_file ---")
    res_file = CodeExecutor.run_file(test_file, logger=_test_logger)
    print(res_file)

    print("\n--- Testing run_project ---")
    res_proj = CodeExecutor.run_project("python executor_test.py", Path("."), logger=_test_logger)
    print(res_proj)

    print("\n--- Testing try_auto_install (mock) ---")
    # This should fail returning False, but we want to verify it doesn't crash
    res_install = CodeExecutor.try_auto_install("No module named 'fake_module_1234'", Path("."), logger=_test_logger)
    print(f"Auto-install fake module result: {res_install}")

finally:
    test_file.unlink()
