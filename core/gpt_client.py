import ast
import os
import pathlib
import textwrap
import time

from openai import OpenAI

from core.logger import get_logger


class GPTClient:
    def __init__(self):
        self.logger = get_logger()
        self._client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

    def generate_new_strategy(self, prompt: str, save_dir: pathlib.Path):
        try:
            resp = self._client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.5,
                timeout=60,
            )
            code = resp.choices[0].message.content
            ast.parse(code)  # validate syntax before saving
            name = f'gpt_strategy_{int(time.time())}.py'
            path = save_dir / name
            save_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(code))
            self.logger.info(f'Generated strategy saved to {path}')
            return path
        except SyntaxError as e:
            self.logger.error(f'GPT returned invalid Python syntax: {e}')
            return None
        except Exception as e:
            self.logger.error(f'GPT generation error: {e}')
            return None
