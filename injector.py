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


def _get_shared_ws_url() -> str | None:
    """Obtiene el webSocketDebuggerUrl del SharedJSContext."""
    try:
        tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()
        target = next((t for t in tabs if t.get("title") == "SharedJSContext"), None)
        return target["webSocketDebuggerUrl"] if target else None
    except Exception:
        return None


def _get_store_ws_url() -> str | None:
    """Obtiene el webSocketDebuggerUrl de la pagina de la store."""
    try:
        tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()
        target = next((t for t in tabs if "store.steampowered.com" in t.get("url", "")), None)
        return target["webSocketDebuggerUrl"] if target else None
    except Exception:
        return None


def _steam_client_call(method: str) -> bool:
    """Busca SharedJSContext y ejecuta un metodo de SteamClient.User ahi."""
    try:
        ws_url = _get_shared_ws_url()
        if not ws_url:
            log("WARN: SharedJSContext no encontrado")
            return False

        ws = create_connection(ws_url, timeout=10)
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


def _inject_csp_and_script(store_ws_url: str, source: str) -> None:
    """Conecta a la store page y configura bypass CSP + script on new document."""
    try:
        ws = create_connection(store_ws_url, timeout=10)
        ws.settimeout(5)
        send_and_wait(ws, 1, "Page.enable", {})
        send_and_wait(ws, 2, "Page.setBypassCSP", {"enabled": True})
        send_and_wait(ws, 3, "Page.addScriptToEvaluateOnNewDocument", {"source": source})
        ws.close()
        log(f"CSP bypass + addScript configurado en store")
    except Exception as e:
        log(f"_inject_csp_and_script error: {e}")


def _inject_js(store_ws_url: str, source: str) -> None:
    """Conecta a la store page y ejecuta el script."""
    try:
        ws = create_connection(store_ws_url, timeout=10)
        ws.settimeout(5)
        r = send_and_wait(ws, 1, "Runtime.evaluate", {"expression": source})
        ws.close()
        log(f"JS inyectado en store: {r.get('result', {}).get('result', {})}")
    except Exception as e:
        log(f"_inject_js error: {e}")


def injector_loop(js_file: pathlib.Path) -> None:
    log("Injector event-driven loop started")

    source = load_content_js(js_file)
    if not source:
        log("WARN: content.js vacio, injector detenido")
        return

    # Estado: mantener bypass CSP activo en la store SIEMPRE
    # El bypass se configura antes de cualquier navegacion para que
    # cuando la pagina cargue, el CSP ya este desactivado.
    store_ws: str | None = None
    store_ws_lock = threading.Lock()

    def _ensure_csp_bypass() -> None:
        """Configura CSP bypass en la store page si no esta hecho ya."""
        nonlocal store_ws
        new_ws = _get_store_ws_url()
        if not new_ws:
            return
        with store_ws_lock:
            if store_ws == new_ws:
                return
            store_ws = new_ws
        log(f"Store target encontrado: {store_ws}")
        _inject_csp_and_script(store_ws, source)

    # Primera configuracion de CSP bypass
    _ensure_csp_bypass()

    while True:
        shared_ws_url = _get_shared_ws_url()
        if not shared_ws_url:
            log("WARN: SharedJSContext no encontrado, reintentando en 2s...")
            time.sleep(2)
            continue

        try:
            ws = create_connection(shared_ws_url, timeout=10)
            ws.settimeout(30)
            log(f"Conectado a SharedJSContext: {shared_ws_url}")

            send_and_wait(ws, 1, "Runtime.enable", {})

            # Runtime.addBinding crea un callback nativo que dispara Runtime.bindingCalled
            send_and_wait(ws, 2, "Runtime.addBinding", {"name": "steamNavigationEvent"})

            # Inyectar event listeners que llaman al binding
            setup_code = """
(function() {
    if (window.__steamNavEventsInstalled) return 'already installed';
    window.__steamNavEventsInstalled = true;

    MainWindowBrowserManager.m_browser.on('finished-request', function() {
        var url = MainWindowBrowserManager.m_URL;
        if (url && url.includes('store.steampowered.com/app/')) {
            steamNavigationEvent(JSON.stringify({event: 'finished-request', url: url}));
        }
    });

    // Inyectar tambien ahora si ya estamos en una store
    var currentUrl = MainWindowBrowserManager.m_URL;
    if (currentUrl && currentUrl.includes('store.steampowered.com/app/')) {
        steamNavigationEvent(JSON.stringify({event: 'finished-request', url: currentUrl}));
    }

    return 'event-driven listeners installed';
})()
"""
            r = send_and_wait(ws, 3, "Runtime.evaluate", {"expression": setup_code})
            log(f"Listeners: {r.get('result', {}).get('result', {}).get('value', 'N/A')}")

            # Bucle principal: escuchar Runtime.bindingCalled
            while True:
                raw = ws.recv()
                data = json.loads(raw)

                if data.get("method") == "Runtime.bindingCalled":
                    name = data.get("params", {}).get("name", "")
                    payload = data.get("params", {}).get("payload", "")
                    if name == "steamNavigationEvent":
                        try:
                            evt = json.loads(payload)
                            evt_type = evt.get("event", "")
                            evt_url = evt.get("url", "")
                            log(f"Binding recibido: {evt_type} -> {evt_url}")

                            if evt_type == "finished-request":
                                # Asegurar que CSP bypass sigue activo (por si el target cambio)
                                _ensure_csp_bypass()
                                with store_ws_lock:
                                    current_store = store_ws
                                if current_store:
                                    threading.Thread(
                                        target=_inject_js,
                                        args=(current_store, source),
                                        daemon=True,
                                    ).start()

                        except json.JSONDecodeError:
                            log(f"Binding payload invalido: {payload}")

        except Exception as e:
            log(f"SharedJSContext connection error: {e}")
            try:
                ws.close()
            except Exception:
                pass

        time.sleep(2)