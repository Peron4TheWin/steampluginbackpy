import json
import time
import logging
import pathlib
import threading

import requests
from websocket import create_connection

log = logging.getLogger().info

CEF_DEBUG_URL = "http://127.0.0.1:8080/json"


def load_content_js(js_file: pathlib.Path) -> str:
    try:
        return js_file.read_text(encoding="utf-8")
    except Exception:
        log("WARN: no se pudo leer content.js")
        return ""


def send_and_wait(ws, msg_id: int, method: str, params: dict) -> dict:
    """Manda un comando CDP y espera la respuesta con el id correcto, ignorando eventos."""
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
    while True:
        raw = ws.recv()
        data = json.loads(raw)
        if data.get("id") == msg_id:
            return data


def watch_tab(ws_url: str, initial_url: str, js_file: pathlib.Path) -> None:
    """
    Mantiene una conexión WS abierta con el tab y escucha eventos de navegación.
    Cuando detecta Page.frameNavigated hacia una store page, inyecta el script.
    Corre en su propio thread por tab.
    """
    try:
        source = load_content_js(js_file)
        if not source:
            return

        ws = create_connection(ws_url, timeout=10)
        ws.settimeout(5)

        # Habilitamos eventos y bypasseamos CSP antes de que llegue cualquier navegación
        send_and_wait(ws, 1, "Page.enable", {})
        send_and_wait(ws, 2, "Page.setBypassCSP", {"enabled": True})
        send_and_wait(ws, 3, "Page.addScriptToEvaluateOnNewDocument", {"source": source})

        # Si la URL actual ya es una store page, inyectamos ahora
        if "store.steampowered.com/app/" in initial_url:
            send_and_wait(ws, 10, "Runtime.evaluate", {"expression": source})
            log(f"Injected (current) into {initial_url}")

        # Escuchamos eventos de navegación
        while True:
            try:
                msg = ws.recv()
                data = json.loads(msg)
                method = data.get("method", "")

                if method == "Page.frameNavigated":
                    frame = data.get("params", {}).get("frame", {})
                    if frame.get("parentId"):
                        continue
                    url = frame.get("url", "")
                    if "store.steampowered.com/app/" not in url:
                        continue
                    log(f"frameNavigated -> {url}, inyectando...")
                    ws.send(json.dumps({
                        "id": 10,
                        "method": "Runtime.evaluate",
                        "params": {"expression": source}
                    }))

            except Exception:
                break

        ws.close()
    except Exception as e:
        log(f"watch_tab error ({ws_url}): {e}")

def _steam_client_call(method: str) -> bool:
    """Busca SharedJSContext y ejecuta un método de SteamClient.User ahí."""
    try:
        tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()
        target = next((t for t in tabs if t.get("title") == "SharedJSContext"), None)
        if not target:
            log("WARN: SharedJSContext no encontrado")
            return False

        ws = create_connection(target["webSocketDebuggerUrl"], timeout=10)
        result = send_and_wait(ws, 1, "Runtime.evaluate", {"expression": f"SteamClient.User.{method}()"})
        ws.close()
        log(f"{method} ejecutado: {result}")
        return True
    except Exception as e:
        log(f"_steam_client_call error: {e}")
        return False


def go_offline() -> bool:
    return _steam_client_call("GoOffline")


def go_online() -> bool:
    return _steam_client_call("GoOnline")

def injector_loop(js_file: pathlib.Path) -> None:
    log("Injector loop started")
    watched: set[str] = set()  # ws_urls que ya tienen un thread activo

    while True:
        try:
            tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()

            for tab in tabs:
                url    = tab.get("url", "")
                ws_url = tab.get("webSocketDebuggerUrl")
                if not url or url in watched:
                    continue
                watched.add(url)
                # Tab nuevo — arrancamos un watcher en background
                watched.add(ws_url)
                t = threading.Thread(
                    target=watch_tab,
                    args=(ws_url, url, js_file),
                    daemon=True,
                )
                t.start()
                log(f"Watching new tab: {url}")

            # Limpiamos tabs cerradas comparando con los ws_url activos
            active = {t.get("webSocketDebuggerUrl") for t in tabs if t.get("webSocketDebuggerUrl")}
            watched &= active

        except Exception as e:
            log(f"[injector] {e}")

        time.sleep(2)