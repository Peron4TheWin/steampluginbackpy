from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pathlib import Path
import requests
import logging
import uvicorn

BASE_DIR = Path(__file__).parent.resolve()
LUA_DIR = BASE_DIR / "config" / "stplug-in"
KEY_FILE = BASE_DIR / "key.txt"
CONTENT_JS = BASE_DIR / "content.js"

app = FastAPI()

logging.basicConfig(
    filename=BASE_DIR / "backend.log",
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
)

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


@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        response = Response(status_code=200)
    else:
        response = await call_next(request)

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"

    return response


@app.get("/script")
async def script():
    if not CONTENT_JS.exists():
        return Response(
            content="Script not available",
            status_code=503
        )

    return Response(
        content=CONTENT_JS.read_bytes(),
        media_type="application/javascript"
    )


@app.get("/status")
async def status():
    return JSONResponse({
        "key_set": bool(get_api_key())
    })


@app.post("/key")
async def key(request: Request):
    key = (await request.body()).decode().strip()

    try:
        r = requests.get(
            "https://hubcapmanifest.com/api/v1/user/stats",
            headers={
                "Authorization": f"Bearer {key}"
            },
            timeout=15,
        )

        if r.status_code == 401:
            return Response(
                content=r.text,
                status_code=401
            )

        r.raise_for_status()

        set_api_key(key)

        return Response(
            content="OK",
            status_code=200
        )

    except requests.HTTPError as e:
        return Response(
            content=str(e),
            status_code=500
        )

    except Exception as e:
        return Response(
            content=f"API error: {e}",
            status_code=500
        )


@app.post("/{appid}")
async def fetch_lua(appid: str):
    try:
        r = requests.get(
            f"https://hubcapmanifest.com/api/v1/lua/{appid}",
            headers={
                "Authorization": f"Bearer {get_api_key()}"
            },
            timeout=30,
        )

        if r.status_code >= 400:
            return Response(
                content=r.text,
                status_code=r.status_code
            )

        LUA_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        out_file = LUA_DIR / f"{appid}.lua"
        out_file.write_bytes(r.content)

        return Response(
            content="OK",
            status_code=200
        )

    except Exception as e:
        return Response(
            content=str(e),
            status_code=500
        )


if __name__ == "__main__":
    print("Listening on 127.0.0.1:3000")

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=3000,
        access_log=False,
        log_config=None
    )