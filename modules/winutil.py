"""Small Windows helpers shared by the bot and the phone API."""


def bring_to_front(hwnd):
    """Show a window on top and give it focus.

    Windows lets only the foreground process take focus, so a background Pulse PC
    first "taps" Alt and attaches to the foreground thread. Raises ValueError with a
    readable message instead of a raw pywin32 error.
    """
    import pywintypes
    import win32api
    import win32con
    import win32gui
    import win32process

    try:
        if not win32gui.IsWindow(hwnd):
            raise ValueError("Окно уже закрыто. Обновите список.")
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        foreground = win32gui.GetForegroundWindow()
        current = win32api.GetCurrentThreadId()
        other = win32process.GetWindowThreadProcessId(foreground)[0] if foreground else 0
        attached = bool(other and other != current)
        if attached:
            win32process.AttachThreadInput(current, other, True)
        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                win32process.AttachThreadInput(current, other, False)
    except pywintypes.error as exc:
        raise ValueError("Windows не разрешила показать окно (ПК заблокирован или окно закрыто).") from exc


def close_foreground_window():
    """Close the active window like Alt+F4, but without key injection (and never the desktop/taskbar,
    where Alt+F4 would open the Windows shutdown dialog). Returns the title of the closed window."""
    import win32con
    import win32gui

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        raise ValueError("Нет активного окна.")
    if win32gui.GetClassName(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        raise ValueError("Сейчас активен рабочий стол Windows: закрывать нечего.")
    title = win32gui.GetWindowText(hwnd)
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    return title
