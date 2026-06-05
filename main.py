import psutil
import subprocess
import time

DEBUG_ARG = "-cef-enable-debugging"

def find_steam():
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == 'steam.exe':
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None

def kill_process_tree(pid):
    try:
        parent = psutil.Process(pid)

        for child in parent.children(recursive=True):
            try:
                child.kill()
            except:
                pass

        parent.kill()

    except:
        pass

while True:
    steam = find_steam()

    if steam:
        cmdline = steam.cmdline()

        if DEBUG_ARG not in cmdline:
            print("Steam sin debugging, reiniciando...")

            steam_path = steam.exe()

            kill_process_tree(steam.pid)

            time.sleep(3)

            subprocess.Popen([
                steam_path,
                DEBUG_ARG
            ])

            print("Steam iniciado con debugging")

    time.sleep(5)