"""Best-effort check for an OS-level handler of the snt:// scheme"""

import ctypes
import subprocess
import sys

from ._swc import SCHEME


def scheme_registered() -> bool | None:
    """True/False if the OS reports a handler for snt://, None if unknown"""
    try:
        if sys.platform == 'darwin':
            return _macos()
        if sys.platform.startswith('win'):
            return _windows()
        if sys.platform.startswith('linux'):
            return _linux()
    except Exception:
        pass
    return None


def _macos() -> bool:
    cf = ctypes.cdll.LoadLibrary(
        '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation'
    )
    cs = ctypes.cdll.LoadLibrary(
        '/System/Library/Frameworks/CoreServices.framework/CoreServices'
    )
    cf.CFURLCreateWithBytes.restype = ctypes.c_void_p
    cf.CFURLCreateWithBytes.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_long,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    cs.LSCopyDefaultApplicationURLForURL.restype = ctypes.c_void_p
    cs.LSCopyDefaultApplicationURLForURL.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    raw = f'{SCHEME}://open'.encode('ascii')
    utf8 = 0x08000100  # kCFStringEncodingUTF8
    url = cf.CFURLCreateWithBytes(None, raw, len(raw), utf8, None)
    if not url:
        raise OSError('Could not create CFURL')
    roles_all = 0xFFFFFFFF  # kLSRolesAll
    return bool(cs.LSCopyDefaultApplicationURLForURL(url, roles_all, None))


def _windows() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, SCHEME) as key:
            winreg.QueryValueEx(key, 'URL Protocol')
        return True
    except FileNotFoundError:
        return False


def _linux() -> bool:
    out = subprocess.run(
        ['xdg-mime', 'query', 'default', f'x-scheme-handler/{SCHEME}'],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return bool(out.stdout.strip())
