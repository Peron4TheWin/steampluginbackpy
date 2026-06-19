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


PERON_EXTRACT_SCRIPT = """
(function() {
    var m = document.body.innerHTML.match(/\\/app\\/(\\d+)\\/properties/);
    return m ? m[1] : '';
})();
"""

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
            # Also inject peron.js if available
            peron_file = js_file.parent / "peron.js"
            peron_source = peron_file.read_text(encoding="utf-8") if peron_file.is_file() else ""
            full_source = source + "\n" + peron_source

            for tab in tabs:
                tab_url = tab.get("url", "")
                if "store.steampowered.com/app/" not in tab_url:
                    continue
                try:
                    tws = create_connection(tab["webSocketDebuggerUrl"], timeout=10)
                    tws.settimeout(5)
                    send_and_wait(tws, 1, "Runtime.evaluate", {"expression": full_source})
                    tws.close()
                    log(f"Injected into existing tab: {tab_url}")
                except Exception:
                    pass

            # Inject Peron into properties tabs for registered games
            _inject_peron_properties(tabs, js_file.parent)

            while True:
                time.sleep(5)
                tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()
                if not any(t.get("title") == "SharedJSContext" for t in tabs):
                    log("SharedJSContext lost, reconnecting...")
                    break
                _inject_peron_properties(tabs, js_file.parent)

        except Exception as e:
            log(f"SharedJSContext error: {e}")
            time.sleep(5)


def _extract_appid(url: str) -> str:
    m = re.search(r"/app/(\d+)/?", url)
    return m.group(1) if m else ""


def _inject_peron_properties(tabs: list, steam_dir: pathlib.Path) -> None:
    peron_js_path = steam_dir / "content_properties.js"
    if not peron_js_path.exists():
        log(f"Peron: content_properties.js not found at {peron_js_path}")
        return
    peron_source = peron_js_path.read_text(encoding="utf-8")

    for tab in tabs:
        tab_url = tab.get("url", "")
        # Properties dialogs have createflags=4114 (or steamloopback in real URL)
        if "createflags=4114" not in tab_url and "steamloopback.host" not in tab_url:
            continue
        # Skip if it's SharedJSContext
        if tab.get("title") == "SharedJSContext":
            continue
        try:
            ws = create_connection(tab["webSocketDebuggerUrl"], timeout=10)
            ws.settimeout(5)
            result = send_and_wait(ws, 1, "Runtime.evaluate", {"expression": PERON_EXTRACT_SCRIPT})
            ws.close()
            val = result.get("result", {}).get("result", {}).get("value", "")
            if not val:
                log(f"Peron: no appId found in {tab.get('title', tab_url)}")
                continue
            appid = str(val)
            log(f"Peron: found appId {appid} in {tab.get('title', tab_url)}")
        except Exception as e:
            log(f"Peron: extract error {e}")
            continue

        # Check if this appid is registered
        try:
            r = requests.get(f"http://127.0.0.1:3000/check/{appid}", timeout=3)
            if r.status_code != 200:
                log(f"Peron: app {appid} not registered ({r.status_code})")
                continue
        except Exception as e:
            log(f"Peron: check error {e}")
            continue

        # Inject Peron
        try:
            ws = create_connection(tab["webSocketDebuggerUrl"], timeout=10)
            ws.settimeout(5)
            send_and_wait(ws, 1, "Runtime.evaluate", {"expression": peron_source})
            ws.close()
            log(f"Peron injected into: {tab.get('title', tab_url)} ({appid})")
        except Exception as e:
            log(f"Peron: inject error {e}")


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