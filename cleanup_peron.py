import json, requests
from websocket import create_connection

tabs = requests.get("http://127.0.0.1:8080/json", timeout=5).json()
target = next((t for t in tabs if "createflags=4114" in t.get("url", "") and t.get("title") != "SharedJSContext"), None)
if not target:
    print("No properties tab found")
    exit()

print(f"Target: {target['title']}")

# Clean old
ws = create_connection(target["webSocketDebuggerUrl"], timeout=10)
ws.settimeout(5)
ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "var els=document.querySelectorAll('[id^=\"peron-\"]');els.forEach(function(e){e.remove()});'removed '+els.length"}}))
while True:
    raw = ws.recv()
    data = json.loads(raw)
    if data.get("id") == 1:
        print("Cleanup:", data.get("result", {}).get("result", {}).get("value", ""))
        break
ws.close()

# Inject
source = open(r"C:\Users\Administrator\Downloads\steamshit\steampluginbackpy\content_properties.js").read()
ws = create_connection(target["webSocketDebuggerUrl"], timeout=10)
ws.settimeout(5)
ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": source}}))
while True:
    raw = ws.recv()
    data = json.loads(raw)
    if data.get("id") == 1:
        err = data.get("result", {}).get("exceptionDetails")
        if err: print("Error:", err.get("text", ""))
        else: print("Injected OK")
        break
ws.close()
