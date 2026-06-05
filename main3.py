from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

import os
import pathlib
import requests
import logging
import uvicorn

# ============================================================
# PATHS
# ============================================================

BASE_DIR = pathlib.Path(__file__).parent

KEY_FILE = BASE_DIR / "key.txt"
PLUGIN_DIR = BASE_DIR / "config" / "stplug-in"
LOG_FILE = BASE_DIR / "backend.log"

PLUGIN_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="[%(asctime)s] %(message)s"
)

log = logging.info

log("=" * 60)
log("Backend started")

# ============================================================
# API KEY
# ============================================================

if not KEY_FILE.exists():
    KEY_FILE.write_text("")


def get_api_key():
    try:
        return KEY_FILE.read_text(
            encoding="utf-8"
        ).strip()
    except:
        return ""


def set_api_key(key: str):
    KEY_FILE.write_text(
        key,
        encoding="utf-8"
    )

    log("API key saved")


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# SAVE KEY
# ============================================================

@app.post("/key")
async def save_key(request: Request):

    try:
        key = (await request.body()).decode().strip()

        r = requests.get(
            "https://hubcapmanifest.com/api/v1/user/stats",
            headers={
                "Authorization": f"Bearer {key}"
            },
            timeout=15
        )

        if r.status_code == 401:
            return Response(
                content=r.text,
                status_code=401
            )

        if r.status_code != 200:
            return Response(
                content=r.text,
                status_code=r.status_code
            )

        set_api_key(key)

        log("Key validated successfully")

        return Response(
            content="OK",
            status_code=200
        )

    except Exception as e:
        log(f"/key error: {e}")

        return Response(
            content=str(e),
            status_code=500
        )


# ============================================================
# DOWNLOAD LUA
# ============================================================

@app.post("/add/{appid}")
async def add_game(appid: str):

    try:
        key = get_api_key()

        if not key:
            return Response(
                content="No API key configured",
                status_code=401
            )

        r = requests.get(
            f"https://hubcapmanifest.com/api/v1/lua/{appid}",
            headers={
                "Authorization": f"Bearer {key}"
            },
            timeout=30
        )

        if r.status_code != 200:
            return Response(
                content=r.text,
                status_code=r.status_code
            )

        out_file = PLUGIN_DIR / f"{appid}.lua"

        out_file.write_bytes(
            r.content
        )

        log(f"Saved {appid}.lua")

        return Response(
            content="OK",
            status_code=200
        )

    except Exception as e:
        log(f"/{appid} error: {e}")

        return Response(
            content=str(e),
            status_code=500
        )

@app.post("/remove/{appid}")
async def remove_game(appid: str):
    out_file = PLUGIN_DIR / f"{appid}.lua"
    try:
        os.remove(out_file)
        return Response(content=f"{appid}.lua removed successfully", status_code=200)
    except OSError as e:
        return Response(content=f"Error: {e} al remover {appid}.lua", status_code=500)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=3000,
        log_level=None,
        log_config=None
    )