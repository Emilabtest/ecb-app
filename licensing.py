"""
Licensing / machine-lock helper (public-key edition).

Each physical machine has a stable Hardware ID (SHA-256 of the Windows
MachineGuid registry key). A licence file (`license.dat`) must contain a valid
RSA-2048 signature over that Hardware ID for the app to start.

Only the PUBLIC key is embedded in this file. Signatures can only be produced
with the owner's PRIVATE key, which lives exclusively in the owner-keys folder
on the owner's machine and is NEVER shipped, committed, or bundled. Extracting
everything from the installed app still does not allow minting licences.

Run as a CLI tool:

    python licensing.py hwid                 # print THIS machine's Hardware ID
    python licensing.py gen <hwid>           # print a licence string for <hwid>
                                             # (owner only: needs private key)

The `gen` mode reads the private key from %LEITURGIA_PRIVATE_KEY% or the
default owner-keys path. The `hwid` mode is safe to run on any target machine
and prints just the Hardware ID.

Signature scheme: RSASSA-PKCS1-v1_5 with SHA-256, implemented with the
standard library only (no third-party dependency is bundled for this).
`license.dat` holds the signature as lowercase hex (512 chars for RSA-2048).
"""
import hashlib
import hmac  # used only for compare_digest; no secret lives in this file
import json
import os
import winreg

# RSA-2048 public key (e, n). Embedded so any copy of the app can VERIFY
# licences and update manifests. This cannot be used to CREATE signatures.
_PUBLIC_E = 65537
_PUBLIC_N = int(
    'aa430527e8beba080dcf2a1b90f06824f7c6a7228112eeca18f3bc05f32cc5cd'
    '1de023dc84bf15453021548df5847da82e3ec5d4bfabef3a5da7d0c33511dcdba'
    '4e1398e3c6017ecce61b531be725eaa0e6e5be2d9456e8bc79a221a65530b733'
    'aebf0165c0de62bbc3d256f7dc161714c789eb9efbde5316b4b4c06e1748633e'
    '9f7e69ad741e013ddc9d3297678d5f022fc819614d3e2de2d3fc318189ebcf4e'
    'c9673d3f325d07abac394958959443b376c2f026068dff47eacde0670b4f4fe4'
    '3d8dbb39ac84cde429753f59072545e674a10cef7957e37ef914fa74ec4acf73'
    '1a51392eec5f1edac0a99982a2949f28c29bc0d9d527cd1aff31a36cb64386b',
    16,
)
_MODULUS_BYTES = 256  # 2048 bits
_SIG_HEX_LEN = _MODULUS_BYTES * 2

# DER prefix of DigestInfo for SHA-256 (PKCS#1 v1.5 padding).
_SHA256_DER_PREFIX = bytes.fromhex(
    '3031300d060960864801650304020105000420'
)

_LICENCE_FILE = 'license.dat'

# Owner-only default location of the private key (never inside a repo or
# installer). Overridable with the LEITURGIA_PRIVATE_KEY env var or the
# key_path argument.
_DEFAULT_KEY_PATH = (
    'C:\\Users\\LIFE HOPE CENTER\\Documents\\Leiturgia-owner-keys'
    '\\leiturgia_private.json'
)


def get_hardware_id():
    """Stable, per-machine identifier (SHA-256 of the Windows MachineGuid)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography') as key:
            value, _ = winreg.QueryValueEx(key, 'MachineGuid')
    except OSError:
        return ''
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()


def _emsa_encode(message):
    """Build the PKCS#1 v1.5 encoded message EM for SHA-256(message)."""
    digest = hashlib.sha256(message).digest()
    t = _SHA256_DER_PREFIX + digest
    if len(t) + 11 > _MODULUS_BYTES:
        raise ValueError('message too long for RSA modulus')
    ps = b'\xff' * (_MODULUS_BYTES - len(t) - 3)
    return b'\x00\x01' + ps + b'\x00' + t


def _load_private_key(key_path=None):
    """Load the owner's private key. Raises a clear error when absent.

    This is only ever called from owner-side code paths (licence issuance,
    update-bundle signing) which run on the owner's machine, never from the
    shipped app's verify paths.
    """
    path = (
        key_path
        or os.environ.get('LEITURGIA_PRIVATE_KEY')
        or _DEFAULT_KEY_PATH
    )
    try:
        with open(path) as f:
            priv = json.load(f)
        d = int(priv['d'], 16)
        n = int(priv['n'], 16)
    except (OSError, KeyError, ValueError, TypeError):
        raise RuntimeError(
            'Owner private key not found or invalid: %s. '
            'Licence issuance and bundle signing only run on the owner machine '
            '(set LEITURGIA_PRIVATE_KEY if the key lives elsewhere).' % path
        )
    if n != _PUBLIC_N:
        raise RuntimeError(
            'Private key does not match the public key embedded in this app.'
        )
    return d, n


def rsa_sign(message, key_path=None):
    """Sign bytes with the owner's private key. Returns lowercase hex."""
    if isinstance(message, str):
        message = message.encode('utf-8')
    d, n = _load_private_key(key_path)
    em = _emsa_encode(message)
    s = pow(int.from_bytes(em, 'big'), d, n)
    return format(s, 'x').zfill(_SIG_HEX_LEN)


def rsa_verify(message, signature_hex):
    """Verify an RSA signature with the embedded public key. No key file."""
    if isinstance(message, str):
        message = message.encode('utf-8')
    try:
        sig = (signature_hex or '').strip().lower()
        if len(sig) != _SIG_HEX_LEN:
            return False
        s = int(sig, 16)
        if not 0 < s < _PUBLIC_N:
            return False
        em = pow(s, _PUBLIC_E, _PUBLIC_N).to_bytes(_MODULUS_BYTES, 'big')
    except (ValueError, OverflowError):
        return False
    if len(em) != _MODULUS_BYTES or not em.startswith(b'\x00\x01'):
        return False
    try:
        sep = em.index(b'\x00', 2)
    except ValueError:
        return False
    if sep < 10:  # PKCS#1 v1.5 requires at least 8 bytes of 0xFF padding
        return False
    if any(b != 0xFF for b in em[2:sep]):
        return False
    expected_t = _SHA256_DER_PREFIX + hashlib.sha256(message).digest()
    return hmac.compare_digest(em[sep + 1:], expected_t)


def make_licence(hardware_id, key_path=None):
    """Return a licence string (RSA signature) authorising a Hardware ID.

    Owner only: requires the private key. The shipped app never calls this.
    """
    return rsa_sign(hardware_id.encode('utf-8'), key_path)


def verify_licence():
    """Return (ok: bool, reason: str) checking this machine is authorised."""
    hwid = get_hardware_id()
    path = os.path.join(os.getcwd(), _LICENCE_FILE)
    if not os.path.isfile(path):
        return (False, 'Missing licence file: %s' % _LICENCE_FILE)
    try:
        with open(path) as f:
            stored = f.read().strip()
    except OSError as e:
        return (False, 'Cannot read licence file: %s' % e)
    if not stored:
        return (False, 'Licence file is empty')
    if not hwid:
        return (False, 'Could not determine this machine hardware ID')
    if not rsa_verify(hwid.encode('utf-8'), stored):
        return (False, 'Licence does not match this machine')
    return (True, 'ok')


def _cli():
    import sys
    args = sys.argv[1:]
    if not args or args[0] == 'hwid':
        print(get_hardware_id())
        return
    if args[0] == 'gen' and len(args) >= 2:
        key_path = args[2] if len(args) >= 3 else None
        try:
            print(make_licence(args[1], key_path))
        except RuntimeError as e:
            print('error: %s' % e)
            sys.exit(1)
        return
    print('usage: licensing.py [hwid|gen <hardware-id> [key-path]]')
    sys.exit(2)


if __name__ == '__main__':
    _cli()
