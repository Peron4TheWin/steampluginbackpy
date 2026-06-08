import json
import time
import pathlib

import requests
from websocket import create_connection

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


def inject(ws_url: str, source: str) -> None:
    try:
        ws = create_connection(ws_url, timeout=5)

        def call(msg_id: int, method: str, params: dict) -> dict:
            ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
            while True:
                data = json.loads(ws.recv())
                if data.get("id") == msg_id:
                    return data

        call(1, "Page.enable", {})
        call(2, "Page.setBypassCSP", {"enabled": True})
        call(3, "Runtime.evaluate", {"expression": source})
        ws.close()
        print("[INJECT] OK")
    except Exception as e:
        print(f"[INJECT] error: {e}")


def _steam_client_call(method: str) -> bool:
    try:
        tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()
        target = next((t for t in tabs if t.get("title") == "SharedJSContext"), None)
        if not target:
            print("WARN: SharedJSContext no encontrado")
            return False
        result = cdp_call(target["webSocketDebuggerUrl"], "Runtime.evaluate", {"expression": f"SteamClient.User.{method}()"})
        print(f"{method} ejecutado: {result}")
        return True
    except Exception as e:
        print(f"_steam_client_call error: {e}")
        return False


def go_offline() -> bool:
    return _steam_client_call("GoOffline")


def go_online() -> bool:
    return _steam_client_call("GoOnline")


def injector_loop(js_file: pathlib.Path) -> None:
    print("[INJECTOR] loop started")
    injected: dict[str, str] = {}

    while True:
        try:
            tabs = requests.get(CEF_DEBUG_URL, timeout=2).json()

            for tab in tabs:
                ws_url = tab.get("webSocketDebuggerUrl")
                url = tab.get("url", "")

                if not ws_url:
                    continue
                if "store.steampowered.com/app/" not in url:
                    continue

                last = injected.get(ws_url)
                if last == url:
                    continue

                print(f"[INJECTOR] nueva store page: {url}")
                source = load_content_js(js_file)
                if source:
                    inject(ws_url, source)
                    injected[ws_url] = url

        except Exception as e:
            print(f"[INJECTOR] error: {e}")

        time.sleep(1)