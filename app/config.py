import json
import uuid
from pathlib import Path

CONFIG_DIR = Path.home() / ".gamebackup"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "key_hex": "",
    "receiver": {
        "port": 5001,
        "dest_folder": "",
        "keep_last_n": 10,
        "enabled": False,
    },
    "profiles": [],
}


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        save_config(json.loads(json.dumps(DEFAULT_CONFIG)))
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    changed = False
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
            changed = True
    if changed:
        save_config(cfg)
    return cfg


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def new_profile(name, save_path, remote_host, remote_port, interval_minutes=30):
    return {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "save_path": save_path,
        "remote_host": remote_host,
        "remote_port": int(remote_port),
        "auto_enabled": False,
        "interval_minutes": int(interval_minutes),
        "last_backup": None,
        "last_status": "Never backed up",
    }
