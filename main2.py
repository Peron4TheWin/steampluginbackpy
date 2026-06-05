import json
import time
import requests
from websocket import create_connection

DEBUG_URL = "http://127.0.0.1:8080/json"

with open("content.js", "r", encoding="utf-8") as f:
    CONTENT_JS = f.read()

last_urls = {}


def inject(ws_url, url):
    try:
        ws = create_connection(ws_url, timeout=5)

        ws.send(json.dumps({
            "id": 1,
            "method": "Page.enable"
        }))
        print(ws.recv())

        ws.send(json.dumps({
            "id": 2,
            "method": "Page.setBypassCSP",
            "params": {
                "enabled": True
            }
        }))
        print(ws.recv())

        ws.send(json.dumps({
            "id": 3,
            "method": "Page.addScriptToEvaluateOnNewDocument",
            "params": {
                "source": CONTENT_JS
            }
        }))
        print(ws.recv())

        ws.send(json.dumps({
            "id": 4,
            "method": "Runtime.evaluate",
            "params": {
                "expression": CONTENT_JS
            }
        }))
        print(ws.recv())

        print(f"[+] Injected into {url}")

        ws.close()
        return True

    except Exception as e:
        print(f"[-] Injection failed for {url}: {e}")
        return False


while True:
    try:
        tabs = requests.get(DEBUG_URL, timeout=2).json()

        active_tabs = set()

        for tab in tabs:
            url = tab.get("url", "")
            ws_url = tab.get("webSocketDebuggerUrl")

            if not ws_url:
                continue

            active_tabs.add(ws_url)

            if "store.steampowered.com/app/" not in url:
                continue

            previous_url = last_urls.get(ws_url)

            if previous_url == url:
                continue

            print(f"[*] URL changed")
            print(f"    Old: {previous_url}")
            print(f"    New: {url}")

            if inject(ws_url, url):
                last_urls[ws_url] = url

        last_urls = {
            ws: url
            for ws, url in last_urls.items()
            if ws in active_tabs
        }

    except Exception as e:
        print(f"[!] {e}")

    time.sleep(1)