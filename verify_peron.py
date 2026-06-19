import json, requests
from websocket import create_connection

tabs = requests.get("http://127.0.0.1:8080/json", timeout=5).json()
for t in tabs:
    url = t.get("url", "")
    if "createflags=4114" not in url and "steamloopback.host" not in url:
        continue
    if t.get("title") == "SharedJSContext":
        continue
    
    print(f"Checking: {t['title']} ({url[:60]})")
    ws = create_connection(t["webSocketDebuggerUrl"], timeout=10)
    ws.settimeout(5)
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "JSON.stringify({peronTab:!!document.getElementById('peron-tab'), peronContent:!!document.getElementById('peron-content'), tabCount:document.querySelectorAll('._1-vlriAtKYDViAEunue4VO').length, tabTexts:Array.from(document.querySelectorAll('._1-vlriAtKYDViAEunue4VO')).map(function(t){return t.textContent.trim().substring(0,30)}), appId:(function(){var m=document.body.innerHTML.match(/\\/app\\/(\\d+)\\/properties/);return m?m[1]:'?'})()})"}}))
    while True:
        raw = ws.recv()
        data = json.loads(raw)
        if data.get("id") == 1:
            print(data.get("result", {}).get("result", {}).get("value", ""))
            break
    ws.close()
