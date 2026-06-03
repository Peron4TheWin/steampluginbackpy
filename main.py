from flask import Flask, request, Response, jsonify
from pathlib import Path
import requests
import logging

BASE_DIR = Path(__file__).parent.resolve()
LUA_DIR = BASE_DIR / "config" / "stplug-in"
KEY_FILE = BASE_DIR / "key.txt"
CONTENT_JS = BASE_DIR / "content.js"

app = Flask(__name__)

logging.basicConfig(
    filename=BASE_DIR / "backend.log",
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
)

# ---------------- API KEY ----------------

if not KEY_FILE.exists():
    KEY_FILE.write_text("")

api_key = KEY_FILE.read_text(encoding="utf-8").strip()


def get_api_key():
    global api_key
    return api_key


def set_api_key(key: str):
    global api_key
    api_key = key.strip()
    KEY_FILE.write_text(api_key, encoding="utf-8")


# ---------------- CORS ----------------

@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    return resp


@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options(path):
    return Response(status=200)


# ---------------- SCRIPT ----------------

@app.get("/script")
def script():
    if not CONTENT_JS.exists():
        return Response("Script not available", status=503)

    return Response(
        CONTENT_JS.read_bytes(),
        mimetype="application/javascript",
    )


# ---------------- STATUS ----------------

@app.get("/status")
def status():
    return jsonify({
        "key_set": bool(get_api_key())
    })


# ---------------- KEY ----------------

@app.post("/key")
def key():
    key = request.get_data(as_text=True).strip()

    try:
        r = requests.get(
            "https://hubcapmanifest.com/api/v1/user/stats",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )

        if r.status_code == 401:
            return Response(r.text, status=401)

        r.raise_for_status()

        set_api_key(key)

        return Response("OK", status=200)

    except requests.HTTPError as e:
        return Response(str(e), status=500)

    except Exception as e:
        return Response(f"API error: {e}", status=500)


# ---------------- APPID ----------------

@app.post("/<appid>")
def fetch_lua(appid):
    try:
        r = requests.get(
            f"https://hubcapmanifest.com/api/v1/lua/{appid}",
            headers={
                "Authorization": f"Bearer {get_api_key()}"
            },
            timeout=30,
        )

        if r.status_code >= 400:
            return Response(r.text, status=r.status_code)

        LUA_DIR.mkdir(parents=True, exist_ok=True)

        out_file = LUA_DIR / f"{appid}.lua"
        out_file.write_bytes(r.content)

        return Response("OK", status=200)

    except Exception as e:
        return Response(str(e), status=500)


# ---------------- MAIN ----------------

if __name__ == "__main__":
    print("Listening on 127.0.0.1:3000")
    app.run(
        host="127.0.0.1",
        port=3000,
        threaded=True,
        debug=False,
    )