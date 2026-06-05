import hashlib
import logging
import pathlib
import sys
import threading

import requests
import uvicorn

from injector import injector_loop
from server import create_app

# ============================================================
# PATHS  (BASE_DIR vive acá para que sys.frozen funcione bien)
# ============================================================

if getattr(sys, "frozen", False):
    BASE_DIR = pathlib.Path(sys.executable).parent
else:
    BASE_DIR = pathlib.Path(__file__).parent

KEY_FILE   = BASE_DIR / "key.txt"
PLUGIN_DIR = BASE_DIR / "config" / "stplug-in"
LOG_FILE   = BASE_DIR / "backend.log"
JS_FILE    = BASE_DIR / "content.js"

PLUGIN_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
)
log = logging.getLogger().info

log("=" * 60)
log("Backend started")

# ============================================================
# KEY FILE — crear si no existe
# ============================================================

if not KEY_FILE.exists():
    KEY_FILE.write_text("")

# ============================================================
# UPDATER  —  content.js
# ============================================================

CONTENT_JS_URL = (
    "https://raw.githubusercontent.com/Peron4TheWin/steampluginfront"
    "/refs/heads/master/content/content.js"
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: pathlib.Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except Exception:
        return ""


def update_content_js() -> None:
    log("Chequeando content.js...")
    try:
        r = requests.get(
            CONTENT_JS_URL,
            timeout=15,
            headers={"User-Agent": "steampluginback/1.0"},
        )
        r.raise_for_status()
        remote = r.content
    except Exception as e:
        log(f"WARN: no se pudo descargar content.js: {e}")
        return

    remote_hash = _sha256_bytes(remote)
    local_hash  = _sha256_file(JS_FILE)
    log(f"content.js local={local_hash[:12]}... remote={remote_hash[:12]}...")

    if local_hash == remote_hash:
        log("content.js ya esta actualizado")
    else:
        JS_FILE.write_bytes(remote)
        log(f"content.js actualizado ({len(remote)} bytes)")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    # 1. Actualizar content.js antes de arrancar
    update_content_js()

    # 2. Injector en background
    threading.Thread(target=injector_loop, args=(JS_FILE,), daemon=True).start()

    # 3. Servidor HTTP
    app = create_app(KEY_FILE, PLUGIN_DIR)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=3000,
        log_level=None,
        log_config=None,
    )