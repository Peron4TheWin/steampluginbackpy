import json
import time
import pathlib
import threading
import requests
from websocket import create_connection, WebSocketTimeoutException

CEF_DEBUG_URL = "http://127.0.0.1:8080/json"

def load_content_js(js_file: pathlib.Path) -> str:
    try:
        return js_file.read_text(encoding="utf-8")
    except Exception:
        print("WARN: no se pudo leer content.js")
        return ""

def cdp_call(ws_url: str, method: str, params: dict) -> dict:
    ws = create_connection(ws_url, timeout=5)
    ws.send(json.dumps({"id": 1, "method": method, "params": params}))
    while True:
        data = json.loads(ws.recv())
        if data.get("id") == 1:
            ws.close()
            return data

def watch_tab(ws_url: str, initial_url: str, js_file: pathlib.Path) -> None:
    ws = create_connection(ws_url, timeout=10)
    msg_id = 1

    def call(method, params):
        nonlocal msg_id
        mid = msg_id
        msg_id += 1
        ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            data = json.loads(ws.recv())
            if data.get("id") == mid:
                return data

    source = load_content_js(js_file)

    call("Page.enable", {})
    # Bypassear CSP para navegaciones FUTURAS
    call("Page.setBypassCSP", {"enabled": True})
    # Inyectar en cada documento nuevo ANTES de que cargue
    call("Page.addScriptToEvaluateOnNewDocument", {"source": source})

    # Para la página actual que ya cargó, forzar reload
    if "store.steampowered.com/app/" in initial_url:
        print(f"[INJECT] recargando para aplicar bypass: {initial_url}")
        call("Page.reload", {})

    # Escuchar navegaciones
    while True:
        raw = ws.recv()
        event = json.loads(raw)
        if event.get("method") == "Page.frameNavigated":
            frame = event["params"]["frame"]
            if frame.get("parentId") is None:  # solo main frame
                url = frame.get("url", "")
                print(f"[WATCH] navegó a: {url}")

def injector_loop(js_file: pathlib.Path) -> None:
    print("[INJECTOR] loop started")
    watched: set[str] = set()

    while True:
        try:
            tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()
            for tab in tabs:
                ws_url = tab.get("webSocketDebuggerUrl")
                url = tab.get("url", "")
                if not ws_url or ws_url in watched:
                    continue
                # Monitorear tabs de store Y tabs nuevos que podrían navegar a store
                # Filtrá por título o URL según lo que Steam te expone
                if "store.steampowered.com" in url or tab.get("title") == "Steam Store":
                    watched.add(ws_url)
                    t = threading.Thread(
                        target=watch_tab,
                        args=(ws_url, url, js_file),
                        daemon=True
                    )
                    t.start()
        except Exception as e:
            print(f"[INJECTOR] error: {e}")
        time.sleep(1)


# go_offline / go_online sin cambios
def _steam_client_call(method: str) -> bool:
    try:
        tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()
        target = next((t for t in tabs if t.get("title") == "SharedJSContext"), None)
        if not target:
            print("WARN: SharedJSContext no encontrado")
            return False
        result = cdp_call(
            target["webSocketDebuggerUrl"],
            "Runtime.evaluate",
            {"expression": f"SteamClient.User.{method}()"}
        )
        print(f"{method} ejecutado: {result}")
        return True
    except Exception as e:
        print(f"_steam_client_call error: {e}")
        return False

def go_offline() -> bool:
    return _steam_client_call("GoOffline")

def go_online() -> bool:
    return _steam_client_call("GoOnline")