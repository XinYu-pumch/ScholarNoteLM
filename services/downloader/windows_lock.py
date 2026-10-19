"""Nonblocking shared/exclusive byte-range locks compatible with Rust fs2.

The MSVCRT LK_NBRLCK constant is exclusive too; use LockFileEx for readers.
Closing the owning file releases the lock, including on process termination.
"""
import ctypes
from ctypes import wintypes
import msvcrt


class Overlapped(ctypes.Structure):
    _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                ('hEvent', wintypes.HANDLE)]


kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
kernel.LockFileEx.restype = wintypes.BOOL


def lock(file, shared=False):
    position = Overlapped()
    if not kernel.LockFileEx(msvcrt.get_osfhandle(file.fileno()),
                             1 if shared else 3, 0, 1, 0, ctypes.byref(position)):
        raise ctypes.WinError(ctypes.get_last_error())
