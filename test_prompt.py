from devbot.llm.tools_schema import build_system_prompt
from devbot.config.settings import load_config, ServiceConfig
cfg = load_config()
cfg.services['openclaw'] = ServiceConfig(
    shell='wsl',
    commands={
        'start': 'cd ~/openclaw && npm start',
        'restart': 'cd ~/openclaw && npm restart',
        'status': 'cd ~/openclaw && npm run status',
        'logs': 'tail -50 ~/openclaw/logs/openclaw.log',
    }
)
print(build_system_prompt(cfg))
