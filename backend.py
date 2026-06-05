import json
import time
import hashlib
import pathlib
import logging
import threading
import os

import requests
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from websocket import create_connection

# ============================================================
# PATHS
# ============================================================

BASE_DIR   = pathlib.Path(__file__).parent
KEY_FILE   = BASE_DIR / "key.txt"
PLUGIN_DIR = BASE_DIR / "config" / "stplug-in"
LOG_FILE   = BASE_DIR / "backend.log"
JS_FILE    = BASE_DIR / "content.js"

PLUGIN_DIR.mkdir(parents=True, exist_ok=True)

CONTENT_JS_URL = (
    "https://raw.githubusercontent.com/Peron4TheWin/steampluginfront"
    "/refs/heads/master/content/content.js"
)
CEF_DEBUG_URL = "http://127.0.0.1:8080/json"

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
# API KEY
# ============================================================

if not KEY_FILE.exists():
    KEY_FILE.write_text("")


def get_api_key() -> str:
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def set_api_key(key: str) -> None:
    KEY_FILE.write_text(key, encoding="utf-8")
    log("API key saved")


# ============================================================
# content.js — descarga y actualización
# ============================================================

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except Exception:
        return ""


def fetch_content_js() -> bytes | None:
    try:
        r = requests.get(CONTENT_JS_URL, timeout=15,
                         headers={"User-Agent": "steampluginback/1.0"})
        r.raise_for_status()
        return r.content
    except Exception as e:
        log(f"WARN: no se pudo descargar content.js: {e}")
        return None


def update_content_js() -> None:
    log("Chequeando content.js...")
    remote = fetch_content_js()
    if remote is None:
        return

    remote_hash = sha256_bytes(remote)
    local_hash  = sha256_file(JS_FILE)
    log(f"content.js local={local_hash[:12]}... remote={remote_hash[:12]}...")

    if local_hash == remote_hash:
        log("content.js ya esta actualizado")
    else:
        JS_FILE.write_bytes(remote)
        log(f"content.js actualizado ({len(remote)} bytes)")


# ============================================================
# INJECTOR
# ============================================================

def load_content_js() -> str:
    try:
        return JS_FILE.read_text(encoding="utf-8")
    except Exception:
        log("WARN: no se pudo leer content.js")
        return ""


def inject(ws_url: str, url: str) -> bool:
    try:
        source = load_content_js()
        if not source:
            return False

        ws = create_connection(ws_url, timeout=5)

        for msg_id, method, params in [
            (1, "Page.enable",         {}),
            (2, "Page.setBypassCSP",   {"enabled": True}),
            (3, "Page.addScriptToEvaluateOnNewDocument", {"source": source}),
            (4, "Runtime.evaluate",    {"expression": source}),
        ]:
            ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
            ws.recv()

        ws.close()
        log(f"Injected into {url}")
        return True

    except Exception as e:
        log(f"Injection failed for {url}: {e}")
        return False


def injector_loop() -> None:
    log("Injector loop started")
    last_urls: dict[str, str] = {}

    while True:
        try:
            tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()
            active_tabs: set[str] = set()

            for tab in tabs:
                url    = tab.get("url", "")
                ws_url = tab.get("webSocketDebuggerUrl")
                if not ws_url:
                    continue

                active_tabs.add(ws_url)

                if "store.steampowered.com/app/" not in url:
                    continue

                if last_urls.get(ws_url) == url:
                    continue

                log(f"URL changed: {last_urls.get(ws_url)} -> {url}")
                if inject(ws_url, url):
                    last_urls[ws_url] = url

            # Limpiamos tabs cerradas
            last_urls = {ws: u for ws, u in last_urls.items() if ws in active_tabs}

        except Exception as e:
            log(f"[injector] {e}")

        time.sleep(1)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/key")
async def save_key(request: Request):
    try:
        key = (await request.body()).decode().strip()
        r = requests.get(
            "https://hubcapmanifest.com/api/v1/user/stats",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
        if r.status_code != 200:
            return Response(content=r.text, status_code=r.status_code)
        set_api_key(key)
        return Response(content="OK", status_code=200)
    except Exception as e:
        log(f"/key error: {e}")
        return Response(content=str(e), status_code=500)


@app.post("/{appid}")
async def add_game(appid: str):
    try:
        key = get_api_key()
        if not key:
            return Response(content="No API key configured", status_code=401)
        r = requests.get(
            f"https://hubcapmanifest.com/api/v1/lua/{appid}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        if r.status_code != 200:
            return Response(content=r.text, status_code=r.status_code)
        (PLUGIN_DIR / f"{appid}.lua").write_bytes(r.content)
        log(f"Saved {appid}.lua")
        return Response(content="OK", status_code=200)
    except Exception as e:
        log(f"/{appid} error: {e}")
        return Response(content=str(e), status_code=500)


@app.post("/remove/{appid}")
async def remove_game(appid: str):
    try:
        os.remove(PLUGIN_DIR / f"{appid}.lua")
        return Response(content=f"{appid}.lua removed", status_code=200)
    except OSError as e:
        return Response(content=f"Error: {e}", status_code=500)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    # 1. Actualizar content.js antes de arrancar
    update_content_js()

    # 2. Injector en background
    threading.Thread(target=injector_loop, daemon=True).start()

    # 3. Servidor HTTP
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=27060,
        log_level=None,
        log_config=None,
    )