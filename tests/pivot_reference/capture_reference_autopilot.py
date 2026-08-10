# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The gesture capture with nobody at the mouse: synthetic input, a screenshot per step, one call.

`capture_reference_gestures.py` records a gesture and `capture_reference_window.py` puts buttons in
front of it, but both still need a hand. This drives the hand as well - it moves the real cursor and
presses the real buttons through the operating system, so Maya cannot tell the difference between
this and a person, which is the whole point: the behaviors left uncaptured are exactly the ones no
command reproduces.

From Maya's Script Editor. The reload is not decoration: a Maya session stays open across a day of
edits to these files, and `import` answers from the cache it filled this morning - which is what an
"unexpected keyword argument" for an argument plainly in the signature on disk actually means. `run`
re-reads what it drives, so only the entry module needs saying out loud:

  import sys, importlib
  sys.path.append(r"S:\\Clarity\\blender\\tests\\pivot_reference")
  import capture_reference_autopilot as autopilot
  importlib.reload(autopilot)
  autopilot.run()

It rebuilds the scene, frames it, and performs every step, writing `<output>.json`, `<output>.log`
and one `<output>_NN_<step>.png` per step next to them. Keep hands off the mouse while it runs; it
takes a few seconds.

What it cannot promise, and does not pretend to: that a synthesized gesture *took*. A drag that
missed the manipulator, a hotkey the viewport did not have focus for, a snap that found nothing -
all of those end as a step that changed nothing, and every step is therefore judged by what actually
moved and by what Maya echoed, not by the fact that the input was sent. `verdict` in each record and
`ЖЕСТ НЕ СРАБОТАЛ` in the log say which ones to distrust; those are the ones to redo by hand through
the window.

Three parts, each replaceable on its own:

* where things are on screen - `M3dView` projects a world point to the viewport, Qt maps the
  viewport to the desktop;
* input - `SendInput` through `ctypes`, because Maya has no command that moves its own mouse, and
  anything short of the operating system's own input queue is a different code path in Maya than the
  one under test;
* the event loop - the script runs *on* Maya's UI thread, so a synthetic event sits in the queue
  until that thread lets go. `_settle()` is that letting go, and it is why every gesture is followed
  by one.
"""

from __future__ import annotations

import ctypes
import importlib
import sys
import time
from pathlib import Path
from typing import Any, Callable

import capture_reference_commands as commands
import capture_reference_gestures as gestures
import capture_reference_pivot as reference
from reference_backend import cmds, mel

_DEFAULT_OUTPUT = Path(__file__).parent / "fixtures" / "maya_2025_pivot_gestures_auto"

# How long a synthesized step waits for Maya to catch up. Generous on purpose: a capture that runs
# for ten seconds and is trustworthy beats one that runs for two and is not.
_SETTLE_SECONDS = 0.12
_DRAG_STEPS = 12


def _say(*values: Any) -> None:
    print("autopilot:", *values)


def refresh_modules() -> None:
    """Re-read the modules this one drives, because a Maya session outlives many edits of them.

    `import` answers from a cache filled when the session first touched these files, and every hour
    spent in the same Maya after an edit is an hour of calling yesterday's code - the failure that
    reads as "unexpected keyword argument" for an argument that is plainly in the signature on disk.

    Unconditionally, including when a session appears to be running: `run` replaces it anyway, and a
    session left behind by a crashed run is indistinguishable from a live one - so a guard here
    would protect precisely the stale module that caused the crash.
    """
    importlib.reload(commands)
    importlib.reload(gestures)
    gestures.set_command_reader(commands.read)


# ---------------------------------------------------------------------------------------------
# The event loop. Everything here runs on Maya's UI thread, and an input event posted from that
# thread is not seen until the thread returns to its loop.
# ---------------------------------------------------------------------------------------------


def _qt_gui():
    try:
        from PySide6 import QtGui  # type: ignore
    except ImportError:
        from PySide2 import QtGui  # type: ignore
    return QtGui


def _qt():
    """Maya's Qt, whichever binding this version ships."""
    try:
        from PySide6 import QtWidgets, QtCore  # type: ignore
        from shiboken6 import wrapInstance  # type: ignore
    except ImportError:  # Maya 2022-2024
        from PySide2 import QtWidgets, QtCore  # type: ignore
        from shiboken2 import wrapInstance  # type: ignore
    return QtWidgets, QtCore, wrapInstance


def _settle(seconds: float = _SETTLE_SECONDS) -> None:
    """Hand the UI thread back so the events just posted are actually processed."""
    QtWidgets, _, _ = _qt()
    application = QtWidgets.QApplication.instance()
    deadline = time.time() + seconds
    while time.time() < deadline:
        if application is not None:
            application.processEvents()
        time.sleep(0.005)
    cmds.refresh()


# ---------------------------------------------------------------------------------------------
# Where things are. A world point, through the active viewport, to a pixel on the desktop.
# ---------------------------------------------------------------------------------------------


def _viewport_widget():
    """One viewport, chosen once, and the same one for everything.

    Maya has three different answers to "the viewport": the panel with focus, the view under the
    cursor that `M3dView.active3dView()` returns, and whatever is actually on screen. In a
    four-panel layout those are three different cameras, and a capture that projects a vertex
    through one while clicking in another measures a viewport nobody is looking at - which is how a
    ten-unit object came out six pixels wide with the default `persp` plainly framing it.

    So: the biggest visible model panel, decided once and remembered, and every coordinate below
    asked of that one.
    """
    import maya.OpenMayaUI as omui  # noqa: N813

    QtWidgets, _, wrap_instance = _qt()
    if _STATE.get("panel") and cmds.control(_STATE["panel"], exists=True):
        pointer = omui.MQtUtil.findControl(_STATE["panel"])
        if pointer is not None:
            return _STATE["panel"], wrap_instance(int(pointer), QtWidgets.QWidget)

    visible = [panel for panel in (cmds.getPanel(visiblePanels=True) or [])
               if cmds.getPanel(typeOf=panel) == "modelPanel"]
    candidates = visible or (cmds.getPanel(type="modelPanel") or [])
    best = None
    for panel in candidates:
        pointer = omui.MQtUtil.findControl(panel)
        if pointer is None:
            continue
        widget = wrap_instance(int(pointer), QtWidgets.QWidget)
        area = widget.width() * widget.height()
        if not widget.isVisible():
            area //= 100  # Last resort rather than a candidate.
        if best is None or area > best[0]:
            best = (area, panel, widget)
    if best is None:
        raise RuntimeError("нет ни одной 3D-панели, автопилоту негде работать")
    _STATE["panel"] = best[1]
    _say("работаю в панели {} ({}x{})".format(best[1], best[2].width(), best[2].height()))
    return best[1], best[2]


def _view():
    """The `M3dView` of *that* panel, not of whatever the cursor last hovered."""
    import maya.OpenMayaUI as omui  # noqa: N813

    panel, _ = _viewport_widget()
    view = omui.M3dView()
    try:
        omui.M3dView.getM3dViewFromModelPanel(panel, view)
        return view
    except Exception:
        return omui.M3dView.active3dView()


def _world_to_desktop(point: list[float]) -> tuple[int, int] | None:
    """The pixel a world point sits on, in desktop coordinates, or None when it is off screen."""
    import maya.OpenMaya as om  # noqa: N813
    import maya.OpenMayaUI as omui  # noqa: N813

    _, QtCore, _ = _qt()
    view = _view()
    x_util = om.MScriptUtil()
    x_util.createFromInt(0)
    x_pointer = x_util.asShortPtr()
    y_util = om.MScriptUtil()
    y_util.createFromInt(0)
    y_pointer = y_util.asShortPtr()
    visible = view.worldToView(om.MPoint(*point[:3]), x_pointer, y_pointer)
    if visible is False:
        return None
    x = int(om.MScriptUtil.getShort(x_pointer))
    y = int(om.MScriptUtil.getShort(y_pointer))

    _, widget = _viewport_widget()
    width, height = widget.width(), widget.height()
    # Belt and braces: the flag says whether the point was clipped, and the rectangle says whether
    # the answer landed anywhere useful. A point behind the camera can satisfy one and not the
    # other, and a gesture aimed at a pixel outside the viewport is a click on whatever else is
    # there - which is the worst way to find out.
    if not (0 <= x <= width and 0 <= y <= height):
        return None
    # `M3dView` counts from the bottom left, Qt from the top left.
    local = QtCore.QPoint(x, height - y)
    point_global = widget.mapToGlobal(local)
    return int(point_global.x()), int(point_global.y())


def _pivot_world() -> list[float]:
    """Where the manipulator is: the authored pivot if there is one, the object's own if not."""
    position = reference._safe(
        "manipPivot position", lambda: cmds.manipPivot(query=True, position=True)
    )
    valid = reference._safe("manipPivot posValid", lambda: cmds.manipPivot(query=True, posValid=True))
    if valid and isinstance(position, list) and len(position) >= 3:
        return [float(value) for value in position[:3]]
    node = _STATE["node"]
    return [float(value) for value in cmds.xform(node, query=True, worldSpace=True, rotatePivot=True)]


def _pivot_pixel() -> tuple[int, int]:
    pixel = _world_to_desktop(_pivot_world())
    if pixel is None:
        raise RuntimeError("пивот вне экрана: автопилот не может за него взяться")
    return pixel


def _vertex_pixels() -> list[tuple[int, tuple[int, int], list[float]]]:
    """Every vertex as (index, pixel, world), skipping the ones the camera cannot see."""
    shape = _STATE["shape"]
    count = cmds.polyEvaluate(shape, vertex=True)
    result = []
    for index in range(int(count)):
        world = cmds.xform(
            "{}.vtx[{}]".format(shape, index), query=True, worldSpace=True, translation=True
        )
        pixel = _world_to_desktop(world)
        if pixel is not None:
            result.append((index, pixel, [float(value) for value in world]))
    return result


def _far_vertex(from_pixel: tuple[int, int], minimum: int = 90):
    """A vertex far enough from the grab point that the drag is unambiguous, the farthest if none."""
    candidates = _vertex_pixels()
    if not candidates:
        raise RuntimeError("ни одной видимой вершины: камера смотрит не туда")

    def distance(entry):
        return ((entry[1][0] - from_pixel[0]) ** 2 + (entry[1][1] - from_pixel[1]) ** 2) ** 0.5

    candidates.sort(key=distance, reverse=True)
    for entry in candidates:
        if distance(entry) >= minimum:
            return entry
    return candidates[0]


# ---------------------------------------------------------------------------------------------
# Input. Native OS events and nothing above them: Maya has no command that moves its own mouse, and
# a Qt event posted straight at a widget takes a different path through Maya than a real click does.
# ---------------------------------------------------------------------------------------------

_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"

_MOUSEEVENTF_MOVE_ABSOLUTE = 0x8001  # MOVE | ABSOLUTE
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_MIDDLEDOWN = 0x0020
_MOUSEEVENTF_MIDDLEUP = 0x0040
_KEYEVENTF_KEYUP = 0x0002

_VK = {
    "V": 0x56,
    "C": 0x43,
    "X": 0x58,
    "D": 0x44,
    "ESC": 0x1B,
    "CTRL": 0x11,
    "SHIFT": 0x10,
}
_MAC_KEY = {
    "V": 9,
    "C": 8,
    "X": 7,
    "D": 2,
    "J": 38,
    "ESC": 53,
    "CTRL": 59,
    "SHIFT": 56,
}

_CG_LEFT_DOWN = 1
_CG_LEFT_UP = 2
_CG_MOUSE_MOVED = 5
_CG_LEFT_DRAGGED = 6
_CG_OTHER_DOWN = 25
_CG_OTHER_UP = 26
_CG_OTHER_DRAGGED = 27
_CG_HID_EVENT_TAP = 0
_CG_LEFT_BUTTON = 0
_CG_CENTER_BUTTON = 2


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


_MAC_API = None
_MAC_MOUSE_BUTTON: str | None = None
_MAC_MOUSE_POSITION = (0, 0)


def _mac_api():
    """ApplicationServices with pointer-sized signatures; ctypes' defaults truncate CGEventRef."""
    global _MAC_API
    if _MAC_API is not None:
        return _MAC_API
    path = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    core_path = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    api = ctypes.cdll.LoadLibrary(path)
    core = ctypes.cdll.LoadLibrary(core_path)
    api.AXIsProcessTrusted.argtypes = []
    api.AXIsProcessTrusted.restype = ctypes.c_bool
    api.CGEventCreateMouseEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        _CGPoint,
        ctypes.c_uint32,
    ]
    api.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    api.CGEventCreateKeyboardEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint16,
        ctypes.c_bool,
    ]
    api.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    api.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    api.CGEventPost.restype = None
    core.CFRelease.argtypes = [ctypes.c_void_p]
    core.CFRelease.restype = None
    api._clarity_core_foundation = core
    _MAC_API = api
    return api


def input_ready() -> str:
    """Name of the native backend, or a useful failure before a capture has replaced the scene."""
    if _IS_WINDOWS:
        return "Windows SendInput"
    if _IS_MACOS:
        if not _mac_api().AXIsProcessTrusted():
            raise RuntimeError(
                "Maya не разрешено управлять мышью. Добавьте Maya в System Settings > Privacy & "
                "Security > Accessibility, перезапустите Maya и повторите прогон."
            )
        return "macOS CoreGraphics"
    raise RuntimeError("автопилот поддерживает только Windows и macOS: " + sys.platform)


def _mac_post(event: int) -> None:
    if not event:
        raise RuntimeError("CoreGraphics не создал событие ввода")
    api = _mac_api()
    try:
        api.CGEventPost(_CG_HID_EVENT_TAP, event)
    finally:
        api._clarity_core_foundation.CFRelease(event)

# What the snap keys are bound to. Maya's own runtime commands, and the same ones a real key press
# runs - the echo of a hand-held `V` is `SnapToPointPress; dR_exitForSnap;` and nothing else.
#
# Sent as commands rather than as key events on purpose. A synthetic key has to be routed by focus
# and by what is under the cursor, and a run where it silently failed to register looks exactly like
# a run where the snap found nothing: both end in `move -r`, a free move, and only the missing
# `snapMode` in the echo tells them apart - which is a distinction the capture cannot afford to
# leave to chance. The mouse stays synthetic, because the drag *is* the thing under test.
_SNAP_COMMANDS = {
    "V": ("SnapToPointPress", "SnapToPointRelease"),
    "C": ("SnapToCurvePress", "SnapToCurveRelease"),
    "X": ("SnapToGridPress", "SnapToGridRelease"),
}


def _hold_begin(hold: str | None) -> None:
    if not hold:
        return
    for token in hold.split("+"):
        if token in _SNAP_COMMANDS:
            reference._safe(
                _SNAP_COMMANDS[token][0],
                lambda token=token: mel.eval(_SNAP_COMMANDS[token][0]),
            )
        else:
            _key(token, True)
    _settle(0.05)


def _hold_end(hold: str | None) -> None:
    if not hold:
        return
    for token in reversed(hold.split("+")):
        if token in _SNAP_COMMANDS:
            reference._safe(
                _SNAP_COMMANDS[token][1],
                lambda token=token: mel.eval(_SNAP_COMMANDS[token][1]),
            )
        else:
            _key(token, False)


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KeyboardInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _InputUnion(ctypes.Union):
    _fields_ = [("mouse", _MouseInput), ("keyboard", _KeyboardInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _InputUnion)]


def _send(structure: _Input) -> None:
    if not _IS_WINDOWS:
        raise RuntimeError("SendInput доступен только на Windows")
    ctypes.windll.user32.SendInput(1, ctypes.byref(structure), ctypes.sizeof(_Input))


def _mouse_to(x: int, y: int) -> None:
    """Move the system cursor in desktop coordinates, dragging while the button is down."""
    global _MAC_MOUSE_POSITION
    if _IS_MACOS:
        _MAC_MOUSE_POSITION = (x, y)
        event_type = {
            "left": _CG_LEFT_DRAGGED,
            "middle": _CG_OTHER_DRAGGED,
        }.get(_MAC_MOUSE_BUTTON, _CG_MOUSE_MOVED)
        button = _CG_CENTER_BUTTON if _MAC_MOUSE_BUTTON == "middle" else _CG_LEFT_BUTTON
        event = _mac_api().CGEventCreateMouseEvent(
            None, event_type, _CGPoint(float(x), float(y)), button
        )
        _mac_post(event)
        return
    metrics = ctypes.windll.user32.GetSystemMetrics
    width, height = metrics(0), metrics(1)
    absolute_x = int(x * 65535 / max(width - 1, 1))
    absolute_y = int(y * 65535 / max(height - 1, 1))
    event = _Input(
        type=0,
        union=_InputUnion(
            mouse=_MouseInput(
                absolute_x, absolute_y, 0, _MOUSEEVENTF_MOVE_ABSOLUTE, 0, None
            )
        ),
    )
    _send(event)


def _mouse_button(down: bool, button: str = "left") -> None:
    global _MAC_MOUSE_BUTTON
    if button not in {"left", "middle"}:
        raise ValueError("неподдерживаемая кнопка мыши: " + button)
    if _IS_MACOS:
        if button == "middle":
            event_type = _CG_OTHER_DOWN if down else _CG_OTHER_UP
            cg_button = _CG_CENTER_BUTTON
        else:
            event_type = _CG_LEFT_DOWN if down else _CG_LEFT_UP
            cg_button = _CG_LEFT_BUTTON
        x, y = _MAC_MOUSE_POSITION
        event = _mac_api().CGEventCreateMouseEvent(
            None, event_type, _CGPoint(float(x), float(y)), cg_button
        )
        _mac_post(event)
        _MAC_MOUSE_BUTTON = button if down else None
        return
    if button == "middle":
        flag = _MOUSEEVENTF_MIDDLEDOWN if down else _MOUSEEVENTF_MIDDLEUP
    else:
        flag = _MOUSEEVENTF_LEFTDOWN if down else _MOUSEEVENTF_LEFTUP
    _send(_Input(type=0, union=_InputUnion(mouse=_MouseInput(0, 0, 0, flag, 0, None))))


def _key(name: str, down: bool) -> None:
    if _IS_MACOS:
        event = _mac_api().CGEventCreateKeyboardEvent(None, _MAC_KEY[name], down)
        _mac_post(event)
        return
    flags = 0 if down else _KEYEVENTF_KEYUP
    _send(_Input(type=1, union=_InputUnion(
        keyboard=_KeyboardInput(_VK[name], 0, flags, 0, None))))


def _focus_viewport() -> None:
    """Maya routes hotkeys by what has focus and decides its active view by what is under the
    cursor, so give it both - the cursor first, because `M3dView.active3dView()` follows it and
    every coordinate below is asked of that view."""
    panel, widget = _viewport_widget()
    centre = widget.mapToGlobal(widget.rect().center())
    _mouse_to(int(centre.x()), int(centre.y()))
    _settle(0.05)
    control = reference._safe(
        "modelPanel control", lambda: cmds.modelPanel(panel, query=True, control=True)
    )
    target = control if isinstance(control, str) and control else panel
    reference._safe("setFocus", lambda: cmds.setFocus(target))
    _settle(0.05)


def click(at: tuple[int, int], hold: str | None = None) -> None:
    _INPUT.append("клик {} hold={}".format(at, hold or "-"))
    _hold_begin(hold)
    _mouse_to(*at)
    _settle(0.05)
    _mouse_button(True)
    _settle(0.05)
    _mouse_button(False)
    _hold_end(hold)
    _settle()


def drag(
    start: tuple[int, int],
    end: tuple[int, int],
    hold: str | None = None,
    button: str = "left",
    release_hold_before_mouse: bool = False,
) -> None:
    """Press at one pixel, walk to another, release - with a modifier held for the whole walk.

    The walk is in steps rather than one jump because a snap follows the pointer: Maya decides what
    is under it while it moves, and a single jump gives it one sample to decide from.
    """
    _INPUT.append("драг {} -> {} ({} px) hold={} button={} release={}".format(
        start, end,
        int(((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5),
        hold or "-", button,
        "modifier-first" if release_hold_before_mouse else "mouse-first"))
    _STATE["last_drag"] = (start, end, hold, button)
    _mouse_to(*start)
    _settle(0.05)
    _hold_begin(hold)
    _mouse_button(True, button)
    _settle(0.05)
    for step in range(1, _DRAG_STEPS + 1):
        x = start[0] + (end[0] - start[0]) * step / _DRAG_STEPS
        y = start[1] + (end[1] - start[1]) * step / _DRAG_STEPS
        _mouse_to(int(round(x)), int(round(y)))
        _settle(0.02)
        # Half way, with the button still down: the one moment that shows the manipulator being
        # dragged and whatever the snap has decided to highlight. After the release it is all gone.
        if step == _DRAG_STEPS // 2:
            _shot("drag")
    _settle(0.05)
    if release_hold_before_mouse:
        _hold_end(hold)
        _settle(0.05)
        _mouse_button(False, button)
    else:
        _mouse_button(False, button)
        _settle(0.05)
        _hold_end(hold)
    _settle()


def drag_tool_change(
    start: tuple[int, int],
    end: tuple[int, int],
    tool: str,
    hold: str | None = None,
) -> None:
    """Change Maya's active tool while a real drag is in flight, then release cleanly."""
    _INPUT.append("драг со сменой инструмента {} -> {} tool={} hold={}".format(
        start, end, tool, hold or "-"
    ))
    _STATE["last_drag"] = (start, end, hold, "left")
    _mouse_to(*start)
    _settle(0.05)
    _hold_begin(hold)
    _mouse_button(True)
    for step in range(1, _DRAG_STEPS // 2 + 1):
        factor = step / _DRAG_STEPS
        _mouse_to(
            int(round(start[0] + (end[0] - start[0]) * factor)),
            int(round(start[1] + (end[1] - start[1]) * factor)),
        )
        _settle(0.02)
    _shot("tool_change_drag")
    cmds.setToolTo(tool)
    _settle(0.05)
    _mouse_button(False)
    _hold_end(hold)
    _settle()


def drag_cancel(
    start: tuple[int, int],
    end: tuple[int, int],
    hold: str | None = None,
    button: str = "left",
) -> None:
    """Begin a real drag, move halfway, press Escape, and release every held input."""
    _INPUT.append("отменённый драг {} -> {} hold={} button={}".format(
        start, end, hold or "-", button
    ))
    _STATE["last_drag"] = (start, end, hold, button)
    _mouse_to(*start)
    _settle(0.05)
    _hold_begin(hold)
    _mouse_button(True, button)
    _settle(0.05)
    for step in range(1, _DRAG_STEPS // 2 + 1):
        factor = step / _DRAG_STEPS
        _mouse_to(
            int(round(start[0] + (end[0] - start[0]) * factor)),
            int(round(start[1] + (end[1] - start[1]) * factor)),
        )
        _settle(0.02)
    _shot("cancel_drag")
    _key("ESC", True)
    _settle(0.03)
    _key("ESC", False)
    _settle(0.05)
    _mouse_button(False, button)
    _hold_end(hold)
    _settle()


# ---------------------------------------------------------------------------------------------
# The run.
# ---------------------------------------------------------------------------------------------

_STATE: dict[str, Any] = {}

# What the last step actually sent to the operating system. In the record next to the world delta it
# answers the question no screenshot can: how many units of scene one pixel of drag was worth, which
# is what tells a wrong-viewport run apart from a wrong-gesture one.
_INPUT: list[str] = []

# Set by `run` for the step it is on, so a gesture deep in the input layer can ask for a picture
# without knowing anything about output paths or step numbers.
_SHOT: Callable[[str], None] | None = None


def _shot(tag: str) -> None:
    if _SHOT is not None:
        reference._safe("screenshot " + tag, lambda: _SHOT(tag))


def _grab_viewport(path: Path) -> bool:
    """The viewport exactly as it is on screen, with the manipulator in it.

    `playblast` renders the scene through the camera and draws no manipulator, no highlight and no
    cursor - which is everything a gesture is about. This grabs the pixels instead, so a screenshot
    finally answers "what did the mouse have under it" rather than only "where did the object end
    up".
    """
    QtWidgets, _, _ = _qt()
    QtGui = _qt_gui()
    _, widget = _viewport_widget()
    application = QtWidgets.QApplication.instance()
    if application is None:
        return False
    handle = widget.window().windowHandle()
    screen = handle.screen() if handle is not None else application.primaryScreen()
    if screen is None:
        return False
    origin = widget.mapToGlobal(widget.rect().topLeft())
    pixmap = screen.grabWindow(0, origin.x(), origin.y(), widget.width(), widget.height())
    if pixmap is None or pixmap.isNull():
        return False

    # Draw the gesture on the picture: where the button went down, where it came up, and what was
    # held. Without it every screenshot of a drag looks like a screenshot of a viewport.
    drag_marks = _STATE.get("last_drag")
    if drag_marks:
        start, end, hold, button = drag_marks
        painter = QtGui.QPainter(pixmap)
        local_start = (start[0] - origin.x(), start[1] - origin.y())
        local_end = (end[0] - origin.x(), end[1] - origin.y())
        pen = QtGui.QPen(QtGui.QColor(255, 70, 70))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(local_start[0], local_start[1], local_end[0], local_end[1])
        painter.drawEllipse(local_end[0] - 7, local_end[1] - 7, 14, 14)
        pen.setColor(QtGui.QColor(90, 220, 90))
        painter.setPen(pen)
        painter.drawEllipse(local_start[0] - 7, local_start[1] - 7, 14, 14)
        painter.setPen(QtGui.QColor(255, 255, 255))
        painter.drawText(
            local_start[0] + 12, local_start[1] - 10,
            "{} -> {}{}  button={}".format(
                start, end, "  hold=" + hold if hold else "", button
            ),
        )
        painter.end()
    return bool(pixmap.save(str(path), "PNG"))


def _screenshot(index: int, name: str, tag: str = "") -> str | None:
    """One picture of the viewport, grabbed if possible and rendered if not."""
    output = Path(_STATE["output"])
    path = output.parent / "{}_{:02d}_{}{}.png".format(
        output.name, index, name, "_" + tag if tag else "")
    if reference._safe("grab " + name, lambda: _grab_viewport(path)) is True:
        return str(path)
    # The grab failed - Maya minimised, a screen that will not give up its pixels - so fall back to
    # what always works, even though it draws no manipulator.
    frame = cmds.currentTime(query=True)
    written = reference._safe(
        "playblast " + name,
        lambda: cmds.playblast(
            frame=frame,
            format="image",
            compression="png",
            completeFilename=str(path),
            forceOverwrite=True,
            viewer=False,
            showOrnaments=True,
            offScreen=True,
            percent=100,
            quality=100,
            widthHeight=(1280, 800),
        ),
    )
    if isinstance(written, dict) and "error" in written:
        return None
    return str(path)


def _reset_pivot() -> None:
    """Put the pivot back where the fixture starts, before every step.

    Steps are questions, not a story: each one has to start where the last one did or its numbers
    mean nothing next to the others. One run made the case - the grid snap left the pivot nineteen
    hundred units out, and every step after it was aimed at something off the object.

    The four channels a drag writes, back to zero: that is exactly the state the initial snapshot
    records, so "unchanged from initial" stays a meaningful thing to say.
    """
    node = _STATE.get("node")
    if not node:
        return
    for attribute in ("rotatePivot", "scalePivot", "rotatePivotTranslate", "scalePivotTranslate"):
        reference._safe(
            "reset " + attribute,
            lambda attribute=attribute: cmds.setAttr(
                "{}.{}".format(node, attribute), 0.0, 0.0, 0.0, type="double3"
            ),
        )
    _settle(0.05)


def _enter_pivot_edit() -> None:
    """`ctxEditMode` and not a synthetic D: the mode toggle is not what is under test here, and a
    command that cannot miss is the right tool for everything that is only setup."""
    reference._safe("ctxEditMode", lambda: mel.eval("ctxEditMode"))
    _settle()


def _verdict(record: dict[str, Any], step: dict[str, Any] | None = None) -> str:
    """Did the gesture do anything at all - measured, not assumed.

    Except where nothing is the right answer. Leaving the pivot mode writes no channel, and calling
    that a failure would send a hand back to redo a step that worked - so a step may declare itself
    an observation, and then what it is judged on is that the state it wanted to look at survived.
    """
    changes = record.get("changes") or {}
    if step is not None and step.get("observation"):
        return "наблюдение записано, изменений и не ожидалось" if not changes else (
            "наблюдение записано, попутно изменилось: {}".format(len(changes)))
    # A gesture that reached Maya and changed nothing is not a gesture that missed. The vertex snap
    # put the pivot on the vertex it was already on, echoed its `move` like any other drag, and was
    # reported as a failure - a hand would then have been sent to redo a step that worked.
    echoed = record.get("commands") or []
    reached = any(
        line.strip().startswith(("move ", "manipPivot", "rotate ", "scale "))
        for line in echoed
    )
    moved = any(key.endswith("manipPivot.position") or key.endswith("manipPivot.orientation")
                or ".rotatePivot" in key or ".scalePivot" in key for key in changes)
    if moved:
        return "жест сработал"
    if step is not None and step.get("hold") and not any("snapMode" in line for line in echoed):
        return ("СНАП НЕ ВКЛЮЧИЛСЯ: в эхе нет snapMode, движение было свободным - "
                "числа этого шага не про снап")
    if changes:
        return "жест сработал частично: пивот не двигался, но что-то изменилось"
    if reached:
        return "жест дошёл до Maya, но состояние не изменилось - пивот уже был в этой точке"
    return "ЖЕСТ НЕ СРАБОТАЛ: ничего не изменилось"


# Each step is the same name and question the hand-driven checklist uses - so the two artifacts are
# comparable - plus the input that performs it.

def _step_drag_free() -> None:
    _enter_pivot_edit()
    start = _pivot_pixel()
    drag(start, (start[0] + 70, start[1] + 40))


def _step_drag_vertex_snap() -> None:
    pivot = _pivot_pixel()
    grab = (pivot[0] + 8, pivot[1] + 8)  # deliberately off centre: that is the question
    _, target, _ = _far_vertex(pivot)
    drag(grab, target, hold="V")


def _step_drag_edge_snap() -> None:
    pivot = _pivot_pixel()
    grab = (pivot[0] + 8, pivot[1] + 8)
    first, second = _two_vertices_away(pivot)
    midpoint = ((first[0] + second[0]) // 2, (first[1] + second[1]) // 2)
    drag(grab, midpoint, hold="C")


def _step_drag_grid_snap() -> None:
    # Beside the object rather than at the corner of the viewport: a corner in a perspective view is
    # the horizon, and one run put the pivot nineteen hundred units away for it. Close enough that
    # the grid point it lands on is a number worth reading.
    pivot = _pivot_pixel()
    target = (pivot[0] - 200, pivot[1] + 150)
    drag(pivot, target, hold="X")


def _step_drag_axis_handle() -> None:
    # Seventy-five pixels out. Thirty and forty-five both landed on the orientation ring and
    # authored `manipPivot -o` instead of moving anything, so the ring owns the near zone and the
    # axis arrow has to be looked for beyond it.
    pivot = _pivot_pixel()
    axis = _axis_pixel_direction()
    grab = (pivot[0] + int(axis[0] * 75), pivot[1] + int(axis[1] * 75))
    _, target, _ = _far_vertex(pivot)
    drag(grab, target, hold="V")


def _step_component_click() -> None:
    pivot = _pivot_pixel()
    _, target, _ = _far_vertex(pivot, minimum=40)
    click(target)


def _step_leave_mode() -> None:
    _enter_pivot_edit()


def _two_vertices_away(from_pixel: tuple[int, int]):
    candidates = _vertex_pixels()

    def distance(entry):
        return ((entry[1][0] - from_pixel[0]) ** 2 + (entry[1][1] - from_pixel[1]) ** 2) ** 0.5

    candidates.sort(key=distance, reverse=True)
    if len(candidates) < 2:
        raise RuntimeError("нужны две видимые вершины, чтобы прицелиться в ребро между ними")
    return candidates[0][1], candidates[1][1]


def _axis_pixel_direction() -> tuple[float, float]:
    """Which way the pivot's X axis points on screen, as a unit vector in pixels."""
    origin = _pivot_world()
    pixel_origin = _world_to_desktop(origin)
    pixel_along = _world_to_desktop([origin[0] + 1.0, origin[1], origin[2]])
    if pixel_origin is None or pixel_along is None:
        return (1.0, 0.0)
    dx = pixel_along[0] - pixel_origin[0]
    dy = pixel_along[1] - pixel_origin[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1.0:
        return (1.0, 0.0)
    return (dx / length, dy / length)


_STEPS: list[dict[str, Any]] = [
    {
        "name": "pivot_drag_free",
        "question": "база: свободный драг оставляет пивот там, где отпустили курсор",
        "actions": [
            "Войти в режим редактирования пивота (ctxEditMode).",
            "Потянуть пивот за центр на 70x40 пикселей без модификаторов.",
        ],
        "perform": _step_drag_free,
    },
    {
        "name": "pivot_drag_vertex_snap",
        "hold": "V",
        "question": "садится ли пивот точно на вершину или сохраняет смещение захвата",
        "actions": [
            "Взяться за манипулятор со смещением 8x8 пикселей от центра.",
            "С зажатым V дотащить его до самой дальней видимой вершины и отпустить.",
        ],
        "perform": _step_drag_vertex_snap,
    },
    {
        "name": "pivot_drag_edge_snap",
        "hold": "C",
        "question": "точно ли на линии ребра и где вдоль него - середина, конец или курсор",
        "actions": [
            "Взяться со смещением 8x8 от центра.",
            "С зажатым C дотащить до середины между двумя дальними вершинами и отпустить.",
        ],
        "perform": _step_drag_edge_snap,
    },
    {
        "name": "pivot_drag_grid_snap",
        "hold": "X",
        "question": "какая точка сетки выигрывает и обнуляется ли вместе с этим высота",
        "actions": [
            "С зажатым X дотащить пивот в нижний левый угол вьюпорта, на сетку.",
        ],
        "perform": _step_drag_grid_snap,
    },
    {
        "name": "pivot_drag_axis_handle_vertex_snap",
        "hold": "V",
        "question": "остаётся ли снап на оси драга или сходит с неё ради вершины",
        "actions": [
            "Взяться за ручку оси X в 45 пикселях от центра манипулятора.",
            "С зажатым V дотащить до дальней вершины, лежащей в стороне от этой оси.",
        ],
        "perform": _step_drag_axis_handle,
    },
    {
        "name": "pivot_orientation_component_click",
        "question": "какую ориентацию оставляет клик по компоненту - против `manipPivot -o`",
        "actions": ["Кликнуть по геометрии в стороне от манипулятора."],
        "perform": _step_component_click,
    },
    {
        "name": "origin_with_authored_pivot",
        "question": "где сидит origin, пока задан авторский пивот - rotatePivot против manipPivot",
        "actions": ["Выйти из режима редактирования пивота, сохранив авторский пивот."],
        "observation": True,
        "perform": _step_leave_mode,
    },
]


def _frame_subject() -> None:
    """Put the subject in front of the camera, and say which camera out loud.

    The fixture sits some twenty units from the origin - a parent at (7, -3, 5) with a negative
    non-uniform scale, and the subject offset again inside it - so the default `persp` looks at
    empty grid, and every gesture below would then be aimed at a pivot nobody can see. `viewFit`
    with no camera fits "the active view", and which view is active while a script runs from the
    Script Editor is exactly the ambiguity this capture cannot afford.
    """
    subject = _STATE["node"]
    panel, _ = _viewport_widget()
    camera = reference._safe(
        "modelPanel camera", lambda: cmds.modelPanel(panel, query=True, camera=True)
    )

    # `viewFit` in its plain form: the selection, in the active view. Its argument list is where two
    # runs were lost - a camera passed positionally is an *object to frame*, and there is no
    # `-camera` flag to pass it as anything else - so nothing is passed at all, and the result is
    # measured instead of assumed.
    cmds.select(subject, replace=True)
    error = reference._safe("viewFit", lambda: cmds.viewFit(animate=False, fitFactor=0.7))
    if isinstance(error, dict) and "error" in error:
        _say("viewFit не сработал:", error["error"])
    _settle(0.3)
    spread, _visible = _pixel_spread()
    if spread >= _TARGET_SPREAD:
        return

    # Placed by hand from the bounding box, then corrected by what it actually produced. `viewPlace`
    # says where the eye is and what it looks at and takes the camera as its argument, with none of
    # the ambiguity above - but how many pixels a given distance yields depends on the field of
    # view, the aspect and the shape of the object, so the distance is not computed once and hoped
    # for: it is measured and divided down until the object is as big as the gestures need.
    _say("после viewFit объект занимает {} px, ставлю камеру сам".format(spread))
    box = reference._safe("exactWorldBoundingBox", lambda: cmds.exactWorldBoundingBox(subject))
    if not (isinstance(box, list) and len(box) >= 6):
        return
    centre = [(box[index] + box[index + 3]) / 2.0 for index in range(3)]
    radius = max(box[index + 3] - box[index] for index in range(3)) * 0.5 or 1.0
    distance = radius * 3.0

    for attempt in range(5):
        eye = (centre[0] + distance, centre[1] + distance * 0.55, centre[2] + distance)
        if isinstance(camera, str) and camera:
            error = reference._safe(
                "viewPlace",
                lambda eye=eye: cmds.viewPlace(camera, eye=eye, lookAt=centre, animate=False),
            )
        else:
            error = reference._safe(
                "viewPlace", lambda eye=eye: cmds.viewPlace(eye=eye, lookAt=centre, animate=False)
            )
        if isinstance(error, dict) and "error" in error:
            _say("viewPlace не сработал:", error["error"])
            return
        _settle(0.2)
        spread, _visible = _pixel_spread()
        _say("попытка {}: дистанция {:.2f}, объект {} px".format(attempt + 1, distance, spread))
        if spread >= _TARGET_SPREAD:
            return
        if spread <= 0:
            distance *= 0.5
            continue
        # Straight proportion, damped: pixels scale with 1/distance, and overshooting into the
        # object is worse than one extra pass.
        distance *= max(0.35, min(0.9, spread / float(_TARGET_SPREAD)))


# How many pixels the subject has to span before aiming at its vertices means anything. Counting
# visible vertices is not a substitute and one run proved it: from far enough away every vertex is
# inside the viewport and the object is six pixels wide, which passes the count and fails
# everything else - a drag of a few pixels then moves the pivot by hundreds of units.
_MINIMUM_SPREAD = 150

# What the framing aims for. Bigger than the gate on purpose: the gate says "this run is not
# hopeless", this says "the object fills enough of the viewport that a vertex is a target and not a
# pixel", which is what a hand would arrange before starting.
_TARGET_SPREAD = 420


def _pixel_spread() -> tuple[int, int]:
    """How wide the subject is on screen, and how many of its vertices are visible at all."""
    visible = _vertex_pixels()
    if len(visible) < 2:
        return 0, len(visible)
    xs = [pixel[0] for _, pixel, _ in visible]
    ys = [pixel[1] for _, pixel, _ in visible]
    return int(max(max(xs) - min(xs), max(ys) - min(ys))), len(visible)


def _check_on_screen() -> None:
    """Refuse to perform seven gestures at something the camera is not looking at.

    A run that misses everything still writes a file full of steps that changed nothing, and that
    file is indistinguishable from a real finding - which is the one outcome worth crashing over.
    """
    try:
        pivot = _pivot_pixel()
    except RuntimeError as error:
        raise RuntimeError("после кадрирования пивот всё ещё вне экрана: {}".format(error))
    spread, visible = _pixel_spread()
    if visible < 3:
        raise RuntimeError(
            "видно вершин: {} - камера смотрит мимо объекта, жесты будут бить в пустоту".format(
                visible
            )
        )
    if spread < _MINIMUM_SPREAD:
        raise RuntimeError(
            "объект занимает {} пикселей при нужных {} - кадрирование не сработало, "
            "смотрите скрин prepare_failed".format(spread, _MINIMUM_SPREAD)
        )
    _say("пивот на экране в {}, видимых вершин {}, объект шириной {} px".format(
        pivot, visible, spread))


def _record_setup() -> None:
    """Write down what this run is actually looking through, in the artifact itself.

    Every wrong answer so far came from the setup, not from a gesture: the wrong panel, a camera
    that never framed anything, an object six pixels wide. All of that was printed to the Script
    Editor and none of it reached the file, so the file could not be read without the console next
    to it. Now it can.
    """
    panel, widget = _viewport_widget()
    spread, visible = _pixel_spread()
    camera = reference._safe(
        "modelPanel camera", lambda: cmds.modelPanel(panel, query=True, camera=True)
    )
    corner = widget.mapToGlobal(widget.rect().topLeft())
    pivot = None
    try:
        pivot = _pivot_pixel()
    except RuntimeError:
        pivot = None
    record = gestures.snapshot(
        "setup",
        extra={
            "automated": True,
            "panel": panel,
            "camera": camera if isinstance(camera, str) else None,
            "viewportSize": [widget.width(), widget.height()],
            "viewportOrigin": [int(corner.x()), int(corner.y())],
            "subjectSpreadPixels": spread,
            "visibleVertices": visible,
            "pivotPixel": list(pivot) if pivot else None,
            "input": [
                "панель {} {}x{} в {},{}, камера {}".format(
                    panel, widget.width(), widget.height(),
                    int(corner.x()), int(corner.y()),
                    camera if isinstance(camera, str) else "?"),
                "объект {} px, видимых вершин {}, пивот в {}".format(spread, visible, pivot),
            ],
        },
    )
    record.pop("adhoc", None)
    commands.drain()
    gestures._relog()
    gestures._write()
    gestures.rebase()


def _prepare_view() -> None:
    """The tool and the camera for the scene the session has already built.

    Deliberately *not* the scene. `gestures.start` builds it - `file -new` and the fixture - and a
    `_prepare` that built one of its own left the session to throw it away and make another, with a
    fresh default camera. Everything then measured a scene that no longer existed: framing that had
    worked, a check that had passed, and an object six pixels wide in every gesture that followed.
    """
    node = _STATE["node"]
    # The panel is chosen fresh for every run: the layout may have changed since the last one, and a
    # remembered panel that is now hidden is exactly the wrong one to measure through.
    _STATE.pop("panel", None)
    cmds.select(node, replace=True)
    reference._safe("setToolTo Move", lambda: cmds.setToolTo("Move"))
    _focus_viewport()
    # Framed and close: every pixel the object is bigger is a pixel of margin for a snap to be
    # unambiguous, and the manipulator has a fixed size in pixels whatever the object does.
    _frame_subject()
    _focus_viewport()
    _check_on_screen()


def run(output: Path | str | None = None, steps: list[dict[str, Any]] | None = None) -> str:
    """Perform every step with no hand on the mouse, and write the artifact."""
    refresh_modules()
    output = Path(output or _DEFAULT_OUTPUT)
    plan = list(steps if steps is not None else _STEPS)

    commands.start(output.with_name(output.name + "_history").with_suffix(".mel"))
    gestures.set_command_reader(commands.read)
    try:
        # The session builds the scene; this only aims a camera at it. In the other order the scene
        # would be built twice and framed once, and the framing would belong to the discarded one.
        gestures.start(output, steps=[])
        session = gestures._SESSION
        _STATE.update({
            "output": output,
            "node": session["node"],
            "shape": session["shape"],
            "child": session["child"],
        })
        commands.drain()
        try:
            _prepare_view()
        except Exception:
            # A screenshot of what the camera was actually looking at, because that is the whole
            # question when a run refuses to start.
            shot = _screenshot(0, "prepare_failed")
            if shot:
                _say("что видела камера:", shot)
            raise
        commands.drain()
        # Diagnostics never kill a run: a capture that lost its notes is still a capture.
        reference._safe("setup", _record_setup)

        for index, step in enumerate(plan, 1):
            _say("шаг {}/{}: {}".format(index, len(plan), step["name"]))
            if not step.get("keep_pivot"):
                _reset_pivot()
                commands.drain()
                # The reset is not the gesture: re-baseline so the record shows only what the
                # gesture did, instead of the reset and the gesture added together.
                gestures.rebase()
            del _INPUT[:]
            _STATE.pop("last_drag", None)
            global _SHOT
            _SHOT = lambda tag, index=index, step=step: _screenshot(index, step["name"], tag)
            shots: dict[str, str] = {}
            before = _screenshot(index, step["name"], "before")
            if before:
                shots["before"] = before
            error = reference._safe(step["name"], step["perform"])
            _settle(0.2)
            _SHOT = None
            screenshot = _screenshot(index, step["name"], "after")
            extra: dict[str, Any] = {
                "instruction": gestures.step_text(step),
                "question": step["question"],
                "automated": True,
            }
            if screenshot:
                shots["after"] = screenshot
                extra["screenshot"] = screenshot
            drag_shot = Path(str(Path(_STATE["output"]))).parent / "{}_{:02d}_{}_drag.png".format(
                Path(_STATE["output"]).name, index, step["name"])
            if drag_shot.exists():
                shots["drag"] = str(drag_shot)
            if shots:
                extra["screenshots"] = shots
            if _INPUT:
                extra["input"] = list(_INPUT)
            if isinstance(error, dict) and "error" in error:
                extra["error"] = error["error"]
            record = gestures.snapshot(step["name"], extra=extra)
            # It went in through the free-capture door because the plan is the autopilot's, not the
            # session's - but it is a step of a checklist and the log should not call it anything else.
            record.pop("adhoc", None)
            verdict = _verdict(record, step)
            record["verdict"] = verdict
            _say("  " + verdict)
            gestures._relog()
            gestures._write()
            commands.drain()

        gestures.finish()
    finally:
        commands.stop()
    _say("готово:", output.with_suffix(".log"))
    return str(output.with_suffix(".log"))
