import os
import logging
import pathlib

import requests
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from injector import go_online, go_offline

log = logging.getLogger().info


# ============================================================
# KEY HELPERS
# ============================================================

def get_api_key(key_file: pathlib.Path) -> str:
    try:
        return key_file.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def set_api_key(key_file: pathlib.Path, key: str) -> None:
    key_file.write_text(key, encoding="utf-8")
    log("API key saved")


# ============================================================
# APP FACTORY
# ============================================================

def create_app(key_file: pathlib.Path, plugin_dir: pathlib.Path) -> FastAPI:

    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ----------------------------------------------------------
    # POST /key  — guarda y valida la API key
    # ----------------------------------------------------------
    @app.post("/key")
    async def save_key(request: Request):
        try:
            key = (await request.body()).decode().strip()
            r = requests.get(
                "https://hubcapmanifest.com/api/v1/user/stats",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
            if r.status_code != 200:
                return Response(content=r.text, status_code=r.status_code)
            set_api_key(key_file, key)
            return Response(content="OK", status_code=200)
        except Exception as e:
            log(f"/key error: {e}")
            return Response(content=str(e), status_code=500)

    # ----------------------------------------------------------
    # POST /{appid}  — descarga y guarda el .lua del juego
    # ----------------------------------------------------------
    @app.post("/{appid}")
    async def add_game(appid: str):
        try:
            key = get_api_key(key_file)
            if not key:
                return Response(content="No API key configured", status_code=401)
            r = requests.get(
                f"https://hubcapmanifest.com/api/v1/lua/{appid}",
                headers={"Authorization": f"Bearer {key}"},
                timeout=30,
            )
            if r.status_code != 200:
                return Response(content=r.text, status_code=r.status_code)
            (plugin_dir / f"{appid}.lua").write_bytes(r.content)
            log(f"Saved {appid}.lua")
            go_offline()
            go_online()
            return Response(content="OK", status_code=200)
        except Exception as e:
            log(f"/{appid} error: {e}")
            return Response(content=str(e), status_code=500)

    # ----------------------------------------------------------
    # POST /remove/{appid}  — elimina el .lua del juego
    # ----------------------------------------------------------
    @app.post("/remove/{appid}")
    async def remove_game(appid: str):
        try:
            os.remove(plugin_dir / f"{appid}.lua")
            go_offline()
            go_online()
            return Response(content=f"{appid}.lua removed", status_code=200)
        except OSError as e:
            return Response(content=f"Error: {e}", status_code=500)

    @app.get("/check/{appid}")
    async def check_game(appid: str):
        try:
            if os.path.isfile(plugin_dir / f"{appid}.lua"):
                return Response(content=f"{appid}.lua exists", status_code=200)
            else:
                return Response(content=f"{appid}.lua does not exist", status_code=404)
        except OSError as e:
            return Response(content=f"Error: {e}", status_code=500)

    @app.get("/limit")
    async def get_limit():
        r = requests.get(
            "https://hubcapmanifest.com/api/v1/user/stats",
            headers={"Authorization": f"Bearer {get_api_key(key_file)}"}
        )
        data = r.json()
        return Response(content=f"{data['daily_usage']}/{data['daily_limit']}",status_code=200)



    return app