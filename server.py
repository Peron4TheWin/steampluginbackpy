import os
import logging
import pathlib
import subprocess
import json

import requests
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from injector import go_online, go_offline, inject_into_tab

log = logging.getLogger().info

import re

def filter_setmanifestid(content: bytes) -> bytes:
    """Comenta lineas setManifestid para que Steam siempre baje la ultima version."""
    text = content.decode("utf-8", errors="replace")
    filtered = re.sub(r"^(setManifestid)", r"-- \1", text, flags=re.MULTILINE)
    return filtered.encode("utf-8")


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

def create_app(key_file: pathlib.Path, plugin_dir: pathlib.Path, js_file: pathlib.Path) -> FastAPI:

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
            (plugin_dir / f"{appid}.lua").write_bytes(filter_setmanifestid(r.content))
            log(f"Saved {appid}.lua")
            # go_offline()   # OST tiene LuaFileWatcher, no hace falta toggle
            # go_online()
            return Response(content="OK", status_code=200)
        except Exception as e:
            log(f"/{appid} error: {e}")
            return Response(content=str(e), status_code=500)

    @app.post("/keyless/{appid}")
    async def add_game(appid: str):
        try:
            r = requests.get(
                f"https://raw.githubusercontent.com/Peron4TheWin/Peronapi/refs/heads/luas/{appid}.lua",
                timeout=30,
            )
            if r.status_code != 200:
                return Response(content=r.text, status_code=r.status_code)
            (plugin_dir / f"{appid}.lua").write_bytes(filter_setmanifestid(r.content))
            log(f"Saved {appid}.lua")
            # go_offline()   # OST tiene LuaFileWatcher, no hace falta toggle
            # go_online()
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
            # go_offline()   # OST tiene LuaFileWatcher
            # go_online()
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

    @app.get("/content")
    async def get_content():
        try:
            return Response(content=js_file.read_text(encoding="utf-8"), media_type="application/javascript")
        except Exception:
            return Response(content="", status_code=500)

    @app.get("/content_properties.js")
    async def get_content_properties():
        try:
            return Response(content=(js_file.parent / "content_properties.js").read_text(encoding="utf-8"), media_type="application/javascript")
        except Exception:
            return Response(content="", status_code=500)

    @app.get("/inject")
    async def inject_route(url: str):
        try:
            source = js_file.read_text(encoding="utf-8")
            peron_file = js_file.parent / "peron.js"
            if peron_file.is_file():
                source += "\n" + peron_file.read_text(encoding="utf-8")
            ok = inject_into_tab(url, source)
            return Response(content="ok" if ok else "tab not found", status_code=200 if ok else 404)
        except Exception as e:
            return Response(content=str(e), status_code=500)

    @app.get("/fixes/{appid}")
    async def get_fixes(appid: str):
        return Response(content='[{"id":"fps_unlock","name":"FPS Unlock"},{"id":"skip_intro","name":"Skip Intro"},{"id":"fov_mod","name":"FOV Mod"}]', media_type="application/json")

    @app.post("/fixes/{appid}/apply")
    async def apply_fix(appid: str, request: Request):
        body = await request.json()
        log(f"Apply fix {body.get('fix')} for {appid}")
        return Response(content="OK", status_code=200)

    @app.get("/denuvo/{appid}")
    async def get_denuvo(appid: str):
        import subprocess, re, pathlib, json as _json
        exe = js_file.parent / "extract_tickets.exe"
        if not exe.exists():
            return Response(content='{"error":"extract_tickets.exe not found"}', status_code=500, media_type="application/json")
        try:
            proc = subprocess.run([str(exe), appid], input="\n", capture_output=True, text=True, timeout=30, cwd=str(exe.parent))
            txt_dir = exe.parent / appid / "tickets.txt"
            if not txt_dir.exists():
                return Response(content='{"error":"no output"}', status_code=500, media_type="application/json")
            raw = txt_dir.read_text()
            appticket = ""
            eticket = ""
            m = re.search(r"appticket\(\d+bytes\):\s*(\S+)", raw)
            if m: appticket = m.group(1)
            m = re.search(r"eticket\(\d+bytes\):\s*(\S+)", raw)
            if m: eticket = m.group(1)

            # POST to remote server to get one-time code
            try:
                r = requests.post(
                    "http://api.perondepot.xyz/denuvo/api/ticket",
                    json={"appid": appid, "appticket": appticket, "eticket": eticket},
                    timeout=10,
                    headers={"Host": "api.perondepot.xyz"},
                )
                if r.status_code == 200:
                    code = r.json().get("code", "")
                    return Response(content=_json.dumps({"code": code}), media_type="application/json")
                else:
                    return Response(content=_json.dumps({"error": f"Remote server: {r.status_code} {r.text}"}), status_code=500, media_type="application/json")
            except Exception as e:
                return Response(content=_json.dumps({"error": f"Remote server unreachable: {e}"}), status_code=500, media_type="application/json")

        except Exception as e:
            return Response(content='{"error":"' + str(e) + '"}', status_code=500, media_type="application/json")

    @app.post("/denuvo/{appid}")
    async def apply_denuvo(appid: str, request: Request):
        import winreg
        body = await request.json()
        code = body.get("code", "").strip().upper()
        if not code:
            return Response(content="No code provided", status_code=400)

        # Redeem code from remote server
        try:
            r = requests.get(
                f"http://api.perondepot.xyz/denuvo/api/ticket/{code}",
                timeout=10,
                headers={"Host": "api.perondepot.xyz"},
            )
            if r.status_code != 200:
                log(f"Apply denuvo: remote returned {r.status_code} {r.text}")
                return Response(content=f"Remote error: {r.status_code} {r.text}", status_code=500)
            data = r.json()
            appticket = data.get("appticket", "")
            eticket = data.get("eticket", "")
            log(f"Apply denuvo for {appid}: redeemed code {code}, AppTicket={len(appticket)}bytes ETicket={len(eticket)}bytes")
        except Exception as e:
            log(f"Apply denuvo: remote fetch error {e}")
            return Response(content=f"Remote unreachable: {e}", status_code=500)

        # Store tickets in registry for OpenSteamTool
        try:
            key_path = f"Software\\Valve\\Steam\\Apps\\{appid}"
            if appticket:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
                winreg.SetValueEx(key, "AppTicket", 0, winreg.REG_BINARY, bytes.fromhex(appticket))
                winreg.CloseKey(key)
                log(f"AppTicket stored in HKCU\\{key_path}")
            if eticket:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
                winreg.SetValueEx(key, "ETicket", 0, winreg.REG_BINARY, bytes.fromhex(eticket))
                winreg.CloseKey(key)
                log(f"ETicket stored in HKCU\\{key_path}")
            return Response(content="OK", status_code=200)
        except Exception as e:
            log(f"Apply denuvo: registry error {e}")
            return Response(content=str(e), status_code=500)

    @app.get("/limit")
    async def get_limit():
        try:
            r = requests.get(
                "https://hubcapmanifest.com/api/v1/user/stats",
                headers={"Authorization": f"Bearer {get_api_key(key_file)}"},
                timeout=15,
            )
            data = r.json()
            return Response(content=f"{data['daily_usage']}/{data['daily_limit']}", status_code=200)
        except Exception as e:
            return Response(content=str(e), status_code=500)


    @app.get("/tickets/{appid}")
    async def get_tickets(appid: str):
        try:
            exe = js_file.parent / "extract_tickets.exe"
            if not exe.is_file():
                return Response(content=json.dumps({"error": "extract_tickets.exe not found"}), status_code=500, media_type="application/json")
            proc = subprocess.run([str(exe), appid], capture_output=True, timeout=30, input="\n", text=True)
            tf = pathlib.Path(appid) / "tickets.txt"
            if not tf.is_file():
                return Response(content=json.dumps({"error": "no tickets, start the game download first"}), status_code=404, media_type="application/json")
            import re
            t = tf.read_text()
            at = re.search(r"appticket\(\d+bytes\):([0-9a-fA-F]+)", t)
            et = re.search(r"eticket\(\d+bytes\):([0-9a-fA-F]+)", t)
            ah = at.group(1) if at else None
            eh = et.group(1) if et else None
            sid = None
            if ah and len(ah) >= 32:
                sid = str(int.from_bytes(bytes.fromhex(ah)[8:16], "little"))
            return Response(content=json.dumps({"appticket": ah, "eticket": eh, "steam_id": sid}), media_type="application/json")
        except Exception as e:
            return Response(content=json.dumps({"error": str(e)}), status_code=500, media_type="application/json")

    return app