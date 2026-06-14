import re

with open('app/services/files/document_service.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace imports
code = re.sub(r'import google\.generativeai as genai', 'from app.services.agents.llm_gateway import LLMGateway\nfrom google.genai import types', code)

# Remove _get_api_key and _gemini_client
code = re.sub(r'def _get_api_key\(\) -> str:.*?def _gemini_client\(\):.*?return genai\.GenerativeModel\("gemini-2\.5-flash"\)', '', code, flags=re.DOTALL)

# Replace audio part creation
code = re.sub(r'\{"mime_type": mime, "data": content\}', 'types.Part.from_bytes(data=content, mime_type=mime)', code)

# Replace model generate content assignments (result)
code = re.sub(r'\s*model\s*=\s*_gemini_client\(\)\s*response\s*=\s*model\.generate_content\((.*?)\)\s*result\s*=\s*response\.text\.strip\(\)', r'\n            result = LLMGateway.generate(\1)', code)

# Replace model generate content assignments (return)
code = re.sub(r'\s*model\s*=\s*_gemini_client\(\)\s*response\s*=\s*model\.generate_content\((.*?)\)\s*return response\.text\.strip\(\)', r'\n            return LLMGateway.generate(\1)', code)

# Some specific instances might not match the general regex due to spacing
code = re.sub(r'model\s*=\s*_gemini_client\(\)', '', code)
code = re.sub(r'response\s*=\s*model\.generate_content\((.*?)\)', r'result = LLMGateway.generate(\1)', code)
code = re.sub(r'result\s*=\s*response\.text\.strip\(\)', '', code)

with open('app/services/files/document_service.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("Refactored successfully")
