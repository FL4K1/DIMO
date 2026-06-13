CODE_WRITE_PROMPT = """You are an expert {language} developer.
Write clean, working, well-commented {language} code for the description below.

Rules:
- Output ONLY the code. No explanation, no markdown, no backticks.
- Add helpful inline comments.
- Handle errors and edge cases properly.
- Use modern best practices.

Description: {description}

Code:"""

CODE_EDIT_PROMPT = """You are an expert code editor.
Apply the following change to the code below.
Return ONLY the complete updated code — no explanation, no markdown, no backticks.

Change: {instruction}

Original code:
{content}

Updated code:"""

CODE_EXPLAIN_PROMPT = """Explain what this code does in simple, clear language.
Focus on: what it does, how it works, and any important details.
Be concise — 3 to 6 sentences maximum.

Code:
{code}

Explanation:"""

CODE_OPTIMIZE_PROMPT = """You are an expert {language} developer and code reviewer.
Optimize the following code for:
1. Performance — eliminate unnecessary operations, use efficient data structures
2. Readability — clear variable names, proper formatting, logical structure
3. Best practices — modern {language} patterns, error handling, type hints if applicable
4. Remove dead code, redundant comments, and unnecessary complexity

Return ONLY the optimized code — no explanation, no markdown, no backticks.

Original code:
{code}

Optimized code:"""

CODE_FIX_PROMPT = """You are an expert debugger.
The code below failed with the following error. Fix it.
Return ONLY the corrected code — no explanation, no markdown, no backticks.

Original goal: {description}

Error:
{error_output}

Broken code:
{code}

Fixed code:"""

CODE_TEST_GENERATE_PROMPT = """You are an expert {language} developer in test-driven development.
Write comprehensive unit tests for the following code.
Use the standard testing framework for {language} (e.g., pytest for Python, Jest for JavaScript).

Rules:
- Output ONLY the complete test code. No explanation, no markdown, no backticks.
- Include happy paths and edge cases.
- Provide necessary imports and mock objects if required.

Original code:
{code}

Unit tests:"""

PROJECT_PLAN_PROMPT = """You are an expert Software Architect.
The user wants to build a project based on the following description.
Plan the project architecture, files, and dependencies.

Rules:
1. Provide a detailed JSON response exactly matching this schema:
{{
  "project_name": "name_of_project",
  "dependencies": ["list", "of", "pip", "packages"],
  "files": [
    {{
      "path": "relative/path/to/file.py",
      "description": "What this file does and its key functions/classes."
    }}
  ]
}}
2. Ensure the entry point is named 'main.py' or 'app.py' or 'index.js' as appropriate.
3. Keep the file structure modular but not overly complex.
4. Output ONLY valid JSON. No markdown backticks around it.

Description: {description}

JSON Plan:"""

PROJECT_FILE_PROMPT = """You are an expert {language} developer.
You are implementing a specific file for a project based on the architecture plan.

Project Plan:
{project_plan}

File to implement: {file_path}
File description: {file_description}

Rules:
- Write the complete, working code for this file.
- Ensure it properly interfaces with the other planned files.
- Output ONLY the raw code. No explanation, no markdown backticks.

Code:"""
