import openai, os, pathlib, textwrap, ast, importlib.util
from core.logger import get_logger
from backtest.backtester import Backtester

class GPTClient:
    def __init__(self):
        self.logger = get_logger()
        openai.api_key = os.getenv('OPENAI_API_KEY')

    def generate_new_strategy(self, prompt: str, save_dir: pathlib.Path):
        try:
            resp = openai.ChatCompletion.create(
                model='gpt-4o-mini',
                messages=[{'role':'user','content':prompt}],
                temperature=0.5
            )
            code = resp.choices[0].message.content
            tree = ast.parse(code)
            name = f'gpt_strategy_{int(os.times().elapsed)}.py'
            path = save_dir/name
            with open(path, 'w') as f:
                f.write(textwrap.dedent(code))
            return path
        except Exception as e:
            self.logger.error(f'GPT generation error {e}')
            return None
