from app.services.agents.code_analyzer import CodeAnalyzer

def test_classify():
    assert CodeAnalyzer.classify_error("Traceback: ZeroDivisionError") == "runtime_error"
    assert CodeAnalyzer.classify_error("ModuleNotFoundError: No module named 'requests'") == "dependency_error"
    assert CodeAnalyzer.classify_error("SyntaxError: invalid syntax") == "syntax_error"
    print("Classify error works")

def test_has_error():
    assert CodeAnalyzer.has_error("Traceback: Error") == True
    assert CodeAnalyzer.has_error("It ran successfully") == False
    assert CodeAnalyzer.has_error("Build failed.") == True
    assert CodeAnalyzer.has_error("Connection timed out") == False
    print("Has error works")

def test_parse_traceback():
    tb = """
Traceback (most recent call last):
  File "C:\\test\\main.py", line 12, in <module>
    foo()
  File "C:\\test\\utils.py", line 42, in foo
    raise ValueError("test")
ValueError: test
"""
    files = ["main.py", "utils.py"]
    file_name, line = CodeAnalyzer.parse_traceback(tb, files)
    assert file_name == "utils.py"
    assert line == 42
    print("Parse traceback works")

def test_extract_module():
    err = "ModuleNotFoundError: No module named 'beautifulsoup4'"
    mod = CodeAnalyzer.extract_missing_module(err)
    assert mod == "beautifulsoup4"
    print("Extract missing module works")

def test_detect_intent():
    assert CodeAnalyzer.detect_intent("make it better", "test.py", "code") == "optimize"
    assert CodeAnalyzer.detect_intent("what does this do", "test.py", "code") == "explain"
    assert CodeAnalyzer.detect_intent("ekrandaki hatayı düzelt", "", "") == "screen_debug"
    assert CodeAnalyzer.detect_intent("create a snake game", "", "") == "write"
    print("Detect intent works")

if __name__ == "__main__":
    test_classify()
    test_has_error()
    test_parse_traceback()
    test_extract_module()
    test_detect_intent()
    print("All CodeAnalyzer tests passed.")
