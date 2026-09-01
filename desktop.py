"""
desktop.py — Windows desktop launcher for Leiturgia.

Starts the embedded Flask server (LeiturgiaServer.exe) as a subprocess, then
opens a native pywebview window pointed at the operator console. Closing the
window stops the server. All runtime state (config.json, data/, media/)
resolves relative to the directory that contains this script, so a packaged
.exe can carry them alongside.
"""
import os
import sys
import time
import subprocess
import socket
import urllib.request as urllib

FROZEN = getattr(sys, 'frozen', False)

if FROZEN:
    APP_DIR = os.path.dirname(sys.executable)
    SERVER = os.path.join(APP_DIR, 'LeiturgiaServer.exe')
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    SERVER = os.path.join(APP_DIR, 'server_entry.py')

HOST = '127.0.0.1'
PORT = 5001
BASE_URL = f'http://{HOST}:{PORT}'
READY_URL = f'{BASE_URL}/api/health'


def _set_cwd():
    os.chdir(APP_DIR)


def _port_in_use(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def _wait_ready(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = urllib.urlopen(READY_URL, timeout=2)
            if r.status == 200:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False

def _terminate_tree(proc):
    try:
        if sys.platform == 'win32':
            subprocess.run(
                ['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                capture_output=True, timeout=10,
            )
        else:
            proc.terminate()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def start_server():
    if _port_in_use(HOST, PORT):
        return None
    if FROZEN:
        cmd = [SERVER]
    else:
        cmd = [sys.executable, SERVER]
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    proc = subprocess.Popen(
        cmd, cwd=APP_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    return proc


def main():
    _set_cwd()

    server_proc = start_server()
    if server_proc is None:
        # A server is already running — open the console without stopping it.
        import webview
        webview.create_window('Leiturgia', BASE_URL)
        webview.start()
        return

    if not _wait_ready():
        _terminate_tree(server_proc)
        return

    import webview
    webview.create_window('Leiturgia', BASE_URL)
    webview.start()
    # Window closed — stop the server we started.
    _terminate_tree(server_proc)


if __name__ == '__main__':
    main()
