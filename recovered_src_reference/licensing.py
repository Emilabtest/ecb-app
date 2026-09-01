# Source Generated with Decompyle++
# File: licensing.pyc (Python 3.12)

"""
Licensing / machine-lock helper.

Each physical machine has a stable Hardware ID (SHA-256 of the Windows
MachineGuid registry key). A licence file (`license.dat`) must contain a valid
HMAC-SHA256 signature over that Hardware ID, produced with the embedded secret
key, for the app to start.

Only the owner (who holds the secret key) can produce a valid licence, so the
app cannot simply be copied to another machine -- each machine needs its own
licence, and only the owner can issue it.

Run as a CLI tool:

    python licensing.py hwid            # print THIS machine's Hardware ID
    python licensing.py gen <hwid>      # print a licence string for <hwid>

The `gen` mode is the owner's tool (it needs the embedded secret). The `hwid`
mode is safe to run on any target machine and prints just the Hardware ID.
"""
import hashlib
import hmac
import os
import winreg
_SECRET_KEY = b'LeiturgiaLock:' + bytes.fromhex('ff449a3813de617262a7e6bbc30bee8fed2c992edeb901a383aca1fc969b5fab')
_LICENCE_FILE = 'license.dat'

def get_hardware_id():
    '''Stable, per-machine identifier (SHA-256 of the Windows MachineGuid).'''
    
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\Microsoft\\Cryptography') as key:
            (guid, _) = winreg.QueryValueEx(key, 'MachineGuid')
    except OSError:
        guid = 'unknown-hardware'

    return hashlib.sha256(str(guid).lower().strip().encode()).hexdigest()


def make_licence(hardware_id):
    '''Return a licence string (HMAC signature) authorising a Hardware ID.'''
    return hmac.new(_SECRET_KEY, hardware_id.encode(), hashlib.sha256).hexdigest()


def verify_licence():
    '''Return (ok: bool, reason: str) checking this machine is authorised.'''
    hwid = get_hardware_id()
    path = os.path.join(os.getcwd(), _LICENCE_FILE)
    if not os.path.isfile(path):
        return (False, f'''Missing licence file: {_LICENCE_FILE}''')
    
    try:
        with open(path, 'r') as f:
            provided = f.read().strip()
    except OSError as e:
        return (False, f'''Cannot read licence file: {e}''')

    expected = make_licence(hwid)
    if not hmac.compare_digest(provided, expected):
        return (False, 'Licence is not valid for this machine')
    return (True, 'ok')
# WARNING: Decompyle incomplete


def _cli():
    import sys
    args = sys.argv[1:]
    if not args or args[0] == 'hwid':
        print(get_hardware_id())
        return None
    if args[0] == 'gen' and len(args) >= 2:
        print(make_licence(args[1]))
        return None
    print('usage: licensing.py [hwid|gen <hardware-id>]')
    sys.exit(2)

if __name__ == '__main__':
    _cli()

