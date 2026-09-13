"""Capture only an explicitly selected visible Roblox window."""
import ctypes
from ctypes import wintypes
import io
import sys
import psutil


def processes():
    found = []
    for proc in psutil.process_iter(['pid', 'name']):
        if (proc.info['name'] or '').lower() in ('robloxplayerbeta.exe', 'robloxstudiobeta.exe'):
            found.append(proc.info)
    return found


def windows():
    if sys.platform != 'win32':
        raise ValueError('Window capture requires Windows')
    user = ctypes.windll.user32
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    allowed = {p['pid'] for p in processes()}
    result = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in allowed and user.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(1024)
            user.GetWindowTextW(hwnd, title, 1024)
            result.append({'pid': pid.value, 'hwnd': int(hwnd), 'title': title.value})
        return True
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows(callback_type(visit), 0)
    return result


def capture(hwnd):
    from PIL import ImageGrab
    if int(hwnd) not in {w['hwnd'] for w in windows()}:
        raise ValueError('Choose a currently visible Roblox HWND from list_windows')
    user = ctypes.windll.user32
    user.IsIconic.argtypes = [wintypes.HWND]
    if user.IsIconic(int(hwnd)):
        raise ValueError('Restore the Roblox window before capturing it')
    # Pillow 11.2+ supports window-specific PrintWindow capture on Windows.
    image = ImageGrab.grab(window=int(hwnd))
    image.thumbnail((1600, 1200))
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()
