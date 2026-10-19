"""File change time: POSIX ctime, Windows FILE_BASIC_INFO.ChangeTime.

Python 3.12's Windows st_ctime is creation time and cannot invalidate caches
after an edit that preserves size and mtime. Keep the POSIX signature unchanged.
"""
import os

if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class BasicInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_longlong) for name in
                    ('creation', 'access', 'write', 'change')] + [('attributes', wintypes.DWORD)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL


def change_ns(path, stat=None, fd=None):
    if os.name != 'nt':
        return (stat or os.stat(path)).st_ctime_ns
    handle = msvcrt.get_osfhandle(fd) if fd is not None else kernel.CreateFileW(
        str(path), 0x80, 7, None, 3, 0x02000000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = BasicInfo()
        if not kernel.GetFileInformationByHandleEx(handle, 0, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return info.change * 100
    finally:
        if fd is None:
            kernel.CloseHandle(handle)
