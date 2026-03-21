"""Verify all 14 projects load from config and their paths exist on disk."""
from devbot.config.settings import load_config
from pathlib import Path

cfg = load_config()

EXPECTED = [
    "aionui", "discord-claude-bot", "discord-coding-bot", "openclaw",
    "custom-nginx", "fast-vue3", "fullstack-notes", "hello-dock",
    "messagewall", "my-node-app", "notes-api", "picron", "pua", "rmbyext",
]

print(f"Projects in config: {len(cfg.projects)}")
assert len(cfg.projects) == 14, f"Expected 14, got {len(cfg.projects)}"

missing_keys = [k for k in EXPECTED if k not in cfg.projects]
assert not missing_keys, f"Missing keys: {missing_keys}"

print(f"{'Project':<22} {'Path exists':<12} Path")
print("-" * 70)
all_ok = True
for name in EXPECTED:
    proj = cfg.projects[name]
    exists = Path(proj.path).exists()
    status = "[OK]  " if exists else "[MISS]"
    if not exists:
        all_ok = False
    print(f"  {name:<20} {status}  {proj.path}")

print()
if all_ok:
    print("[PASS] All 14 projects loaded and paths exist.")
else:
    print("[WARN] Some paths don't exist yet (normal if project not cloned).")
