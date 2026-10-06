"""Independent snapshots with shared disk blocks on macOS/APFS.

Never hard-link mutable user assets. clonefile provides copy-on-write isolation;
unsupported filesystems/platforms fall back to the existing atomic byte copy.
"""
import ctypes
import os
import shutil
import sys
import uuid


def clone(source, target):
    if sys.platform != 'darwin':
        return False
    lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    fn = lib.clonefile
    fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    fn.restype = ctypes.c_int
    return fn(os.fsencode(source), os.fsencode(target), 0) == 0


def save_image(source, target, data, save):
    """Verify an immutable snapshot before reuse and the cloned bytes before publish."""
    if target.is_symlink():
        raise ValueError('图片快照不能使用符号链接')
    if target.is_file():
        if target.read_bytes() != data:
            raise ValueError('已有图片快照内容校验失败')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name('.' + target.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        if clone(source, temp) and temp.read_bytes() == data:
            os.replace(temp, target)
        else:
            save(target, data)
    finally:
        temp.unlink(missing_ok=True)


def copy2(source, target):
    """copytree hook: preserve shared extents on same-volume project moves."""
    if clone(source, target):
        shutil.copystat(source, target)
        return target
    return shutil.copy2(source, target)
