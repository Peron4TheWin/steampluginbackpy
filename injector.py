import json
import socket
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
    """Conecta a la store page, re-aplica bypass CSP y ejecuta el script."""
    try:
        ws = create_connection(store_ws_url, timeout=10)
        ws.settimeout(5)
        send_and_wait(ws, 1, "Page.enable", {})
        send_and_wait(ws, 2, "Page.setBypassCSP", {"enabled": True})
        r = send_and_wait(ws, 3, "Runtime.evaluate", {"expression": source})
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

    store_ws: str | None = None
    store_ws_lock = threading.Lock()

    def _ensure_csp_bypass() -> None:
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

    # Bloquear hasta que la store este disponible, luego configurar CSP bypass
    while _get_store_ws_url() is None:
        log("WARN: Store page no encontrada, reintentando en 2s...")
        time.sleep(2)
    _ensure_csp_bypass()

    # Flag en Python para evitar reinstalar listeners cada vez que se reconecta
    listeners_installed = False

    while True:
        shared_ws_url = _get_shared_ws_url()
        if not shared_ws_url:
            log("WARN: SharedJSContext no encontrado, reintentando en 2s...")
            time.sleep(2)
            continue

        try:
            ws = create_connection(shared_ws_url, timeout=10)
            ws.settimeout(5)
            log(f"Conectado a SharedJSContext: {shared_ws_url}")

            send_and_wait(ws, 1, "Runtime.enable", {})
            send_and_wait(ws, 2, "Runtime.addBinding", {"name": "steamNavigationEvent"})

            if not listeners_installed:
                # Limpiar flag viejo que pueda quedar en el contexto JS
                send_and_wait(ws, 10, "Runtime.evaluate", {
                    "expression": "delete window.__steamNavEventsInstalled; 'cleaned'"
                })

                setup_code = """
(function() {
    if (window.__steamNavEventsInstalled) return 'already installed';
    try {
        var MBM = window.MainWindowBrowserManager || MainWindowBrowserManager;
        if (!MBM || !MBM.m_browser) throw new Error('MainWindowBrowserManager not accessible');

        window.__steamNavEventsInstalled = true;
        MBM.m_browser.on('finished-request', function() {
            var url = MBM.m_URL;
            if (url && url.includes('store.steampowered.com/app/')) {
                steamNavigationEvent(JSON.stringify({event: 'finished-request', url: url}));
            }
        });
        var currentUrl = MBM.m_URL;
        if (currentUrl && currentUrl.includes('store.steampowered.com/app/')) {
            steamNavigationEvent(JSON.stringify({event: 'finished-request', url: currentUrl}));
        }
        return true;
    } catch(e) {
        return 'ERROR: ' + e.toString();
    }
})()
"""
                r = send_and_wait(ws, 3, "Runtime.evaluate", {"expression": setup_code})
                val = r.get('result', {}).get('result', {}).get('value', None)
                if isinstance(val, str) and val.startswith('ERROR'):
                    log(f"Listeners: {val}")
                elif val is True:
                    log("Listeners: instalados correctamente")
                    listeners_installed = True
                    # Inyectar JS ahora porque el binding inicial
                    # se lo comio send_and_wait durante la espera de ID 3
                    with store_ws_lock:
                        current_store = store_ws
                    if current_store:
                        threading.Thread(
                            target=_inject_js, args=(current_store, source),
                            daemon=True,
                        ).start()
                else:
                    log(f"Listeners: {val}")

            # Bucle de eventos
            while True:
                try:
                    raw = ws.recv()
                except socket.timeout:
                    continue

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
                                _ensure_csp_bypass()
                                with store_ws_lock:
                                    current_store = store_ws
                                if current_store:
                                    threading.Thread(
                                        target=_inject_js, args=(current_store, source),
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