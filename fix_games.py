import os
import re

source = r'Mark-XXXIX-OR-main/actions/game_updater.py'
target = r'app/services/external/games.py'

with open(source, 'r', encoding='utf-8') as f:
    content = f.read()

# carefully remove print statements while preserving the newline of the previous line
content = re.sub(r'^[ \t]*print\(\s*f?\"\[GameUpdater\].*?\)\n', '', content, flags=re.MULTILINE)
content = re.sub(r'^[ \t]*if player:.*?\n', '', content, flags=re.MULTILINE)
content = re.sub(r'^[ \t]*if speak:.*?\n', '', content, flags=re.MULTILINE)

content = content.replace('def game_updater(parameters: dict, player=None, speak=None) -> str:', 
                          'class GameLibraryService:\n    def execute(self, parameters: dict) -> str:')

parts = content.split('class GameLibraryService:\n    def execute(self, parameters: dict) -> str:\n')
if len(parts) == 2:
    body = parts[1]
    body = '\n'.join(['    ' + line if line else line for line in body.split('\n')])
    content = parts[0] + 'class GameLibraryService:\n    def execute(self, parameters: dict) -> str:\n' + body

with open(target, 'w', encoding='utf-8') as f:
    f.write(content)
