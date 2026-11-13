"""Windows integration used by CPAH.

This module intentionally contains all Win32-specific capture, input, window and
global-hotkey behavior so screenshot analysis and the solver remain testable.
"""

from __future__ import annotations

import ctypes
import pathlib
import time
from ctypes import wintypes
from typing import Callable, Dict, Iterable, Optional, Tuple

import win32api  # type: ignore
import win32con  # type: ignore
import win32gui  # type: ignore
import win32process  # type: ignore
from PIL import Image, ImageGrab
from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication


GAME_EXECUTABLE = "cyberpunk2077.exe"


class WindowNotFoundError(RuntimeError):
    pass


class HotkeyRegistrationError(RuntimeError):
    pass


def enable_per_monitor_dpi_awareness() -> None:
    """Opt into physical screen coordinates before Qt creates any windows."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def _window_executable(hwnd: int) -> Optional[str]:
    try:
        _, process_id = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
            False,
            process_id,
        )
        try:
            return pathlib.Path(win32process.GetModuleFileNameEx(handle, 0)).name.lower()
        finally:
            handle.Close()
    except Exception:
        return None


def find_game_window(title_fallback: str = "") -> int:
    matches = []

    def collect(hwnd: int, _: object) -> None:
        if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd):
            return
        if _window_executable(hwnd) == GAME_EXECUTABLE:
            matches.append(hwnd)

    win32gui.EnumWindows(collect, None)
    if matches:
        return matches[0]
    if title_fallback:
        hwnd = win32gui.FindWindow(None, title_fallback)
        if hwnd:
            return hwnd
    raise WindowNotFoundError(
        f"Game window not found (expected {GAME_EXECUTABLE})"
    )


def focus_game_window(title_fallback: str = "", delay_ms: int = 400) -> int:
    hwnd = find_game_window(title_fallback)
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    if hwnd != win32gui.GetForegroundWindow():
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(delay_ms / 1000)
    return hwnd


def client_bounds(hwnd: int) -> Tuple[int, int, int, int]:
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    _, _, width, height = win32gui.GetClientRect(hwnd)
    return left, top, left + width, top + height


def capture_window(hwnd: int) -> Image.Image:
    bounds = client_bounds(hwnd)
    # Keep the game cursor away from detection regions.
    win32api.SetCursorPos((max(bounds[0], bounds[2] - 1), max(bounds[1], bounds[3] - 1)))
    return ImageGrab.grab(bbox=bounds, all_screens=True).convert("RGB")


_VK_NAMES = {
    "up": win32con.VK_UP,
    "down": win32con.VK_DOWN,
    "left": win32con.VK_LEFT,
    "right": win32con.VK_RIGHT,
    "enter": win32con.VK_RETURN,
    "return": win32con.VK_RETURN,
    "escape": win32con.VK_ESCAPE,
    "esc": win32con.VK_ESCAPE,
    "space": win32con.VK_SPACE,
    "home": win32con.VK_HOME,
    "end": win32con.VK_END,
    "pageup": win32con.VK_PRIOR,
    "pagedown": win32con.VK_NEXT,
    **{f"f{i}": win32con.VK_F1 + i - 1 for i in range(1, 25)},
}


def virtual_key(name: str) -> int:
    normalized = name.strip().lower()
    if normalized in _VK_NAMES:
        return _VK_NAMES[normalized]
    if len(normalized) == 1:
        value = ctypes.windll.user32.VkKeyScanW(ord(normalized))
        if value != -1:
            return value & 0xFF
    raise ValueError(f"Unsupported key: {name}")


def validate_key(name: str) -> str:
    virtual_key(name)
    return name.strip().lower()


def send_key(name: str, delay_ms: int = 17) -> None:
    key = virtual_key(name)
    win32api.keybd_event(key, 0, 0, 0)
    win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(delay_ms / 1000)


_HOTKEY_MODIFIERS = {
    "alt": win32con.MOD_ALT,
    "control": win32con.MOD_CONTROL,
    "ctrl": win32con.MOD_CONTROL,
    "shift": win32con.MOD_SHIFT,
    "super": win32con.MOD_WIN,
    "win": win32con.MOD_WIN,
    "windows": win32con.MOD_WIN,
}


def validate_hotkey(keys: Iterable[str], prefix_only: bool = False) -> Tuple[str, ...]:
    normalized = tuple(key.strip().lower() for key in keys if key.strip())
    if not normalized:
        return normalized
    non_modifiers = [key for key in normalized if key not in _HOTKEY_MODIFIERS]
    expected = 0 if prefix_only else 1
    if len(non_modifiers) != expected:
        kind = "modifier-only prefix" if prefix_only else "modifiers plus one key"
        raise ValueError(f"Hotkey must contain {kind}")
    for key in non_modifiers:
        virtual_key(key)
    return normalized


class GlobalHotkeyManager(QAbstractNativeEventFilter):
    """Small Qt-integrated wrapper around RegisterHotKey/WM_HOTKEY."""

    def __init__(self) -> None:
        super().__init__()
        self._next_id = 0xC000
        self._binds: Dict[Tuple[str, ...], Tuple[int, Callable]] = {}
        self._callbacks: Dict[int, Callable] = {}
        app = QCoreApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self)

    @property
    def keybinds(self) -> Tuple[Tuple[str, ...], ...]:
        return tuple(self._binds)

    def register(self, keys: Iterable[str], callback: Callable) -> None:
        bind = validate_hotkey(keys)
        if not bind or bind in self._binds:
            if bind in self._binds:
                raise HotkeyRegistrationError(f"Hotkey already registered: {' + '.join(bind)}")
            return
        modifiers = win32con.MOD_NOREPEAT
        trigger = None
        for key in bind:
            if key in _HOTKEY_MODIFIERS:
                modifiers |= _HOTKEY_MODIFIERS[key]
            else:
                trigger = virtual_key(key)
        hotkey_id = self._next_id
        self._next_id += 1
        if not ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers, trigger):
            raise HotkeyRegistrationError(f"Hotkey is unavailable: {' + '.join(bind)}")
        self._binds[bind] = (hotkey_id, callback)
        self._callbacks[hotkey_id] = callback

    def unregister(self, keys: Iterable[str]) -> None:
        bind = tuple(keys)
        registered = self._binds.pop(bind, None)
        if registered:
            hotkey_id, _ = registered
            ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
            self._callbacks.pop(hotkey_id, None)

    def close(self) -> None:
        for bind in tuple(self._binds):
            self.unregister(bind)

    def nativeEventFilter(self, event_type, message):  # type: ignore[override]
        if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == win32con.WM_HOTKEY:
                callback = self._callbacks.get(int(msg.wParam))
                if callback:
                    callback(None)
                    return True, 0
        return False, 0
