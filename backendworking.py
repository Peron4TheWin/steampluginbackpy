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

# ========== CONFIGURACIÓN ==========
BASE_DIR = pathlib.Path(__file__).parent
KEY_FILE = BASE_DIR / "key.txt"
PLUGIN_DIR = BASE_DIR / "config" / "stplug-in"
LOG_FILE = BASE_DIR / "backend.log"
JS_FILE = BASE_DIR / "content.js"
PLUGIN_DIR.mkdir(parents=True, exist_ok=True)

CONTENT_JS_URL = "https://raw.githubusercontent.com/Peron4TheWin/steampluginfront/refs/heads/master/content/content.js"
CEF_DEBUG_URL = "http://127.0.0.1:8080/json"

# ========== LOGGING ==========
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
)
log = logging.getLogger().info
log("=" * 60)
log("Backend iniciado")

# ========== API KEY ==========
if not KEY_FILE.exists():
    KEY_FILE.write_text("")

def get_api_key() -> str:
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""

def set_api_key(key: str) -> None:
    KEY_FILE.write_text(key, encoding="utf-8")
    log("API key guardada")

# ========== MANEJO DE CONTENT.JS ==========
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: pathlib.Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except Exception:
        return ""

def fetch_content_js() -> bytes | None:
    try:
        r = requests.get(CONTENT_JS_URL, timeout=15, headers={"User-Agent": "steamplugin/1.0"})
        r.raise_for_status()
        return r.content
    except Exception as e:
        log(f"WARN: no se pudo descargar content.js: {e}")
        return None

def update_content_js() -> None:
    log("Actualizando content.js...")
    remote = fetch_content_js()
    if remote is None:
        return
    remote_hash = sha256_bytes(remote)
    local_hash = sha256_file(JS_FILE)
    if local_hash == remote_hash:
        log("content.js ya está actualizado")
    else:
        JS_FILE.write_bytes(remote)
        log(f"content.js actualizado ({len(remote)} bytes)")

def load_content_js() -> str:
    try:
        return JS_FILE.read_text(encoding="utf-8")
    except Exception:
        log("ERROR: no se pudo leer content.js")
        return ""

# ========== INYECTOR SIMPLE Y EFECTIVO ==========
def inject_into_tab(ws_url: str, source: str) -> bool:
    """Conecta, ejecuta el script, cierra. Timeout 3 segundos."""
    try:
        ws = create_connection(ws_url, timeout=3)
        cmd = json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": source}
        })
        ws.send(cmd)
        ws.settimeout(2)
        raw = ws.recv()
        ws.close()
        data = json.loads(raw)
        if "result" in data:
            # Verificar si hubo error de ejecución
            if data["result"].get("exceptionDetails"):
                log(f"Error en JS: {data['result']['exceptionDetails']}")
                return False
            log("✓ Script inyectado correctamente")
            return True
        else:
            log(f"Respuesta inesperada: {data}")
            return False
    except Exception as e:
        log(f"Error inyectando en {ws_url}: {e}")
        return False

def injector_loop() -> None:
    """Cada 3 segundos, obtiene todas las pestañas e inyecta en las que son store."""
    log("Injector loop iniciado (cada 3 segundos)")
    while True:
        try:
            # Obtener lista de pestañas del depurador remoto
            resp = requests.get(CEF_DEBUG_URL, timeout=2)
            if resp.status_code != 200:
                log(f"CEF debug endpoint respondió {resp.status_code}")
                time.sleep(3)
                continue
            tabs = resp.json()
            source = load_content_js()
            if not source:
                time.sleep(3)
                continue

            for tab in tabs:
                url = tab.get("url", "")
                ws_url = tab.get("webSocketDebuggerUrl")
                if ws_url and "store.steampowered.com/app/" in url:
                    log(f"Procesando: {url}")
                    inject_into_tab(ws_url, source)
        except Exception as e:
            log(f"Error en injector_loop: {e}")
        time.sleep(3)

# ========== FASTAPI ==========
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

# ========== MAIN ==========
if __name__ == "__main__":
    update_content_js()
    threading.Thread(target=injector_loop, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=3000, log_level="warning")