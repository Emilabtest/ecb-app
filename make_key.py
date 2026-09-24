"""Leiturgia license maker (owner tool).

Generates an RSA license key for a customer's Hardware ID.
Run as:  make_key.exe [hwid]   (or paste the HWID when prompted)

Needs the owner private key (Leiturgia-owner-keys). Never ship this exe
to customers.
"""
import sys

from licensing import get_hardware_id, make_licence


def _prompt_hwid():
    print('Leiturgia License Maker (RSA)')
    print('Paste the Hardware ID from the customer activation page (64 hex chars).')
    try:
        hwid = input('HWID> ').strip()
    except EOFError:
        return ''
    return hwid


def main():
    hwid = sys.argv[1].strip() if len(sys.argv) > 1 else _prompt_hwid()
    hwid = hwid.replace(' ', '').replace('-', '').lower()
    if not hwid:
        print('error: no hardware ID given')
        return 1
    if len(hwid) != 64 or any(c not in '0123456789abcdef' for c in hwid):
        print('error: HWID must be 64 hex characters (got %d chars)' % len(hwid))
        print('got: %s' % hwid)
        return 1
    try:
        key = make_licence(hwid)
    except RuntimeError as e:
        print('error: %s' % e)
        return 1
    print()
    print(key)
    print()
    # Best-effort clipboard copy (Windows).
    try:
        import subprocess
        p = subprocess.run(
            ['powershell', '-NoProfile', '-Command', 'Set-Clipboard -Value $args[0]'],
            input=key, capture_output=True, text=True, timeout=15,
            creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0),
        )
        if p.returncode == 0:
            print('(copied to clipboard)')
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
