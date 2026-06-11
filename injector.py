import json
import re
import time
import logging
import pathlib

import requests
from websocket import create_connection

log = logging.getLogger().info

CEF_DEBUG_URL = "http://127.0.0.1:8080/json"


def send_and_wait(ws, msg_id: int, method: str, params: dict) -> dict:
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
    while True:
        raw = ws.recv()
        data = json.loads(raw)
        if data.get("id") == msg_id:
            return data


MONITOR_SCRIPT = """
console.log('monitor script loaded');
setTimeout(function() {
    var retries = 300;
    function check() {
        if (typeof MainWindowBrowserManager !== 'undefined' && MainWindowBrowserManager.m_browser) {
            MainWindowBrowserManager.m_browser.on("finished-request", function(url) {
                if (url && url.indexOf('store.steampowered.com/app/') !== -1) {
                    fetch('http://127.0.0.1:27060/inject?url=' + encodeURIComponent(url)).catch(function(){});
                }
            });
            console.log('monitor hooked on browser');
            return;
        }
        if (--retries > 0) setTimeout(check, 1000);
    }
    check();
}, 10000);
"""


def setup_shared_context(js_file: pathlib.Path) -> None:
    log("SharedJSContext injector started, waiting for SharedJSContext...")

    while True:
        try:
            tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()
            target = next((t for t in tabs if t.get("title") == "SharedJSContext"), None)
            if not target:
                time.sleep(2)
                continue

            ws = create_connection(target["webSocketDebuggerUrl"], timeout=10)
            ws.settimeout(5)
            send_and_wait(ws, 1, "Runtime.evaluate", {"expression": MONITOR_SCRIPT})
            ws.close()
            log("SharedJSContext monitor injected")

            source = js_file.read_text(encoding="utf-8")
            for tab in tabs:
                tab_url = tab.get("url", "")
                if "store.steampowered.com/app/" not in tab_url:
                    continue
                try:
                    tws = create_connection(tab["webSocketDebuggerUrl"], timeout=10)
                    tws.settimeout(5)
                    send_and_wait(tws, 1, "Runtime.evaluate", {"expression": source})
                    tws.close()
                    log(f"Injected into existing tab: {tab_url}")
                except Exception:
                    pass

            while True:
                time.sleep(10)
                tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()
                if not any(t.get("title") == "SharedJSContext" for t in tabs):
                    log("SharedJSContext lost, reconnecting...")
                    break

        except Exception as e:
            log(f"SharedJSContext error: {e}")
            time.sleep(5)


def _extract_appid(url: str) -> str:
    m = re.search(r"/app/(\d+)/?", url)
    return m.group(1) if m else ""


def inject_into_tab(target_url: str, source: str) -> bool:
    try:
        tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()
        target_appid = _extract_appid(target_url)

        target = next((t for t in tabs if t.get("url", "") == target_url), None)
        if not target and target_appid:
            target = next((t for t in tabs if _extract_appid(t.get("url", "")) == target_appid), None)
        if not target:
            log(f"Tab no encontrado para: {target_url}")
            return False

        ws = create_connection(target["webSocketDebuggerUrl"], timeout=10)
        ws.settimeout(5)
        send_and_wait(ws, 1, "Runtime.evaluate", {"expression": source})
        ws.close()
        log(f"Injected into {target_url}")
        return True
    except Exception as e:
        log(f"inject_into_tab error: {e}")
        return False


def _steam_client_call(method: str) -> bool:
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