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
    """Se suscribe a eventos de un tab y reinyecta en cada navegación."""
    try:
        ws = create_connection(ws_url, timeout=10)
        msg_id = 1

        def call(method: str, params: dict) -> dict:
            nonlocal msg_id
            ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
            # Drainear hasta encontrar la respuesta, ignorando eventos
            while True:
                data = json.loads(ws.recv())
                if data.get("id") == msg_id:
                    msg_id += 1
                    return data

        def do_inject(url: str):
            source = load_content_js(js_file)
            if not source:
                return
            # setBypassCSP ANTES del evaluate
            call("Page.setBypassCSP", {"enabled": True})
            call("Runtime.evaluate", {"expression": source, "awaitPromise": False})
            print(f"[INJECT] OK → {url}")

        call("Page.enable", {})
        call("Runtime.enable", {})

        # Inyectar en la URL actual si ya es una store page
        if "store.steampowered.com/app/" in initial_url:
            do_inject(initial_url)

        # Escuchar navegaciones futuras
        while True:
            try:
                ws.settimeout(30)
                raw = ws.recv()
                event = json.loads(raw)
                method = event.get("method", "")

                if method == "Page.domContentEventFired":
                    # Obtener URL actual
                    result = call("Runtime.evaluate", {
                        "expression": "window.location.href",
                        "returnByValue": True
                    })
                    current_url = result.get("result", {}).get("result", {}).get("value", "")
                    if "store.steampowered.com/app/" in current_url:
                        do_inject(current_url)

            except WebSocketTimeoutException:
                # Chequear si el tab sigue vivo
                continue
            except Exception as e:
                print(f"[WATCH] tab cerrado o error: {e}")
                break

        ws.close()
    except Exception as e:
        print(f"[WATCH] error conectando a {ws_url}: {e}")


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