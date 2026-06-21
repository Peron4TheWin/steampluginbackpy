import os
import logging
import pathlib
import json

import requests
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

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
            ok = inject_into_tab(url, source)
            return Response(content="ok" if ok else "tab not found", status_code=200 if ok else 404)
        except Exception as e:
            return Response(content=str(e), status_code=500)

    def _find_game_dir(appid: str, steam_dir: pathlib.Path) -> pathlib.Path | None:
        """Busca la carpeta de instalacion del juego en las library folders de Steam"""
        import winreg
        # Check common install paths via libraryfolders.vdf
        vdf_path = steam_dir / "steamapps" / "libraryfolders.vdf"
        libs = [steam_dir]
        if vdf_path.exists():
            import re
            for line in vdf_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = re.search(r'"path"\s+"(.+)"', line)
                if m: libs.append(pathlib.Path(m.group(1).replace("\\\\", "\\")))
        
        for lib in libs:
            manifest = lib / "steamapps" / f"appmanifest_{appid}.acf"
            if manifest.exists():
                for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
                    m = re.search(r'"installdir"\s+"(.+)"', line)
                    if m:
                        return lib / "steamapps" / "common" / m.group(1)
        return None

    @app.post("/crack/{appid}/install")
    async def install_crack(appid: str):
        """Descarga y extrae el crack en la carpeta del juego con progreso SSE"""
        async def event_stream():
            import zipfile, io, asyncio
            zip_url = f"http://api.perondepot.xyz/mirror/fixedluas/{appid}.zip"
            
            # 1. Find game folder
            yield f"data: {json.dumps({'status':'finding','pct':0})}\n\n"
            await asyncio.sleep(0)
            # Find Steam dir via registry
            import winreg as _wr
            steam_dir_f = js_file.parent
            try:
                for rk, k in [(_wr.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (_wr.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
                              (_wr.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam")]:
                    with _wr.OpenKey(rk, k) as key:
                        steam_dir_f = pathlib.Path(_wr.QueryValueEx(key, "SteamPath")[0].strip('"'))
                        break
            except: pass
            game_dir = _find_game_dir(appid, steam_dir_f)
            if not game_dir:
                yield f"data: {json.dumps({'status':'error','msg':'Game folder not found. Is it installed?'})}\n\n"
                return
            
            # 2. Download zip with progress
            yield f"data: {json.dumps({'status':'downloading','pct':0,'msg':'Downloading crack...'})}\n\n"
            try:
                r = requests.get(zip_url, stream=True, timeout=120)
                r.raise_for_status()
                total = int(r.headers.get('content-length', 0))
                downloaded = 0
                chunks = []
                last_pct = -1
                for chunk in r.iter_content(chunk_size=65536):
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = min(99, int(downloaded / total * 100))
                        if pct > last_pct:
                            last_pct = pct
                            yield f"data: {json.dumps({'status':'downloading','pct':pct,'msg':f'Downloading... {pct}%'})}\n\n"
                            await asyncio.sleep(0)
            except Exception as e:
                yield f"data: {json.dumps({'status':'error','msg':f'Download failed: {e}'})}\n\n"
                return
            
            # 3. Extract
            yield f"data: {json.dumps({'status':'extracting','pct':99,'msg':'Extracting...'})}\n\n"
            try:
                data = b''.join(chunks)
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    z.extractall(game_dir)
                yield f"data: {json.dumps({'status':'done','pct':100,'msg':f'Crack installed to {game_dir}'})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'status':'error','msg':f'Extract failed: {e}'})}\n\n"
        
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/fixes/{appid}")
    async def get_fixes(appid: str):
        try:
            # Use stream=True and close immediately - just check status
            r = requests.get(
                f"http://api.perondepot.xyz/mirror/fixedluas/{appid}.zip",
                timeout=10,
                stream=True,
            )
            available = r.status_code == 200
            r.close()
            if available:
                return Response(content=json.dumps({"available": True, "url": f"http://api.perondepot.xyz/mirror/fixedluas/{appid}.zip"}), media_type="application/json")
            return Response(content=json.dumps({"available": False}), media_type="application/json")
        except:
            return Response(content=json.dumps({"available": False}), media_type="application/json")

    @app.post("/fixes/{appid}/apply")
    async def apply_fix(appid: str, request: Request):
        body = await request.json()
        log(f"Apply fix {body.get('fix')} for {appid}")
        return Response(content="OK", status_code=200)

    @app.get("/denuvo/{appid}")
    async def get_denuvo(appid: str):
        import subprocess,json
        exe = js_file.parent / "extract_tickets.exe"
        if not exe.exists():
            return Response(content='{"error":"extract_tickets.exe not found"}', status_code=500, media_type="application/json")
        try:
            proc = subprocess.run([str(exe), "--pipe", appid], capture_output=True, text=True, timeout=30)
            parts = proc.stdout.strip().split("|")
            if len(parts) < 4:
                return Response(content='{"error":"no output"}', status_code=500, media_type="application/json")
            _, appticket, eticket, steam_id = parts[0], parts[1], parts[2], parts[3]

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
                    return Response(content=json.dumps({"code": code}), media_type="application/json")
                else:
                    return Response(content=json.dumps({"error": f"Remote server: {r.status_code} {r.text}"}), status_code=500, media_type="application/json")
            except Exception as e:
                return Response(content=json.dumps({"error": f"Remote server unreachable: {e}"}), status_code=500, media_type="application/json")

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


    @app.post("/fixed/{appid}")
    async def add_fixed(appid: str):
        """Descarga el lua fijo (con setManifestid) para versiones crackeadas"""
        try:
            r = requests.get(
                f"http://api.perondepot.xyz/mirror/fixedluas/{appid}.lua",
                timeout=30,
            )
            if r.status_code != 200:
                return Response(content="No fixed lua available", status_code=404)
            # NO filtrar setManifestid - los luas fijos los necesitan
            (plugin_dir / f"{appid}.lua").write_bytes(r.content)
            log(f"Saved fixed {appid}.lua")
            return Response(content="OK", status_code=200)
        except Exception as e:
            log(f"/fixed/{appid} error: {e}")
            return Response(content=str(e), status_code=500)

    @app.get("/hascrack/{appid}")
    async def has_crack(appid: str):
        """Chequea si existe un crack (zip) para este appid"""
        try:
            r = requests.get(
                f"http://api.perondepot.xyz/mirror/fixedluas/{appid}.zip",
                timeout=10,
            )
            if r.status_code == 200:
                return Response(content='{"available":true}', media_type="application/json")
            return Response(content='{"available":false}', media_type="application/json")
        except:
            return Response(content='{"available":false}', media_type="application/json")

    @app.get("/hasfixed/{appid}")
    async def has_fixed(appid: str):
        """Chequea si existe un lua fijo para este appid"""
        try:
            r = requests.get(
                f"http://api.perondepot.xyz/mirror/fixedluas/{appid}.lua",
                timeout=10,
            )
            if r.status_code == 200:
                return Response(content='{"available":true}', media_type="application/json")
            return Response(content='{"available":false}', media_type="application/json")
        except:
            return Response(content='{"available":false}', media_type="application/json")

    return app