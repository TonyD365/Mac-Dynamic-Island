"""Keep a window visible above the lock screen.

Uses the same private SkyLight calls other notch utilities rely on: the window is moved into a
dedicated window-server space whose level sits above the lock screen. If any of it is missing on
this macOS version, attach() returns False and the island simply stays an ordinary overlay.
"""
import ctypes

import objc
from Foundation import NSArray

_LEVEL_ABOVE_LOCK_SCREEN = 400
_space = None


def attach(window_number):
    global _space
    try:
        sky = ctypes.CDLL("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight")
        i32, ptr = ctypes.c_int32, ctypes.c_void_p
        sky.SLSMainConnectionID.restype = i32
        sky.SLSSpaceCreate.argtypes, sky.SLSSpaceCreate.restype = [i32, i32, i32], i32
        sky.SLSSpaceSetAbsoluteLevel.argtypes = [i32, i32, i32]
        sky.SLSShowSpaces.argtypes = [i32, ptr]
        sky.SLSSpaceAddWindowsAndRemoveFromSpaces.argtypes = [i32, i32, ptr, i32]
    except (OSError, AttributeError):
        return False
    connection = sky.SLSMainConnectionID()
    if _space is None:
        _space = sky.SLSSpaceCreate(connection, 1, 0)
        if not _space:
            _space = None
            return False
        sky.SLSSpaceSetAbsoluteLevel(connection, _space, _LEVEL_ABOVE_LOCK_SCREEN)
        spaces = NSArray.arrayWithObject_(_space)
        sky.SLSShowSpaces(connection, objc.pyobjc_id(spaces))
    windows = NSArray.arrayWithObject_(int(window_number))
    sky.SLSSpaceAddWindowsAndRemoveFromSpaces(connection, _space, objc.pyobjc_id(windows), 7)
    return True
