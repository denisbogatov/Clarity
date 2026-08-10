# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""A window in Maya for recording what a tool does - automatically, by hand, or one after the other.

Three modes, in the order they are reached for:

* `Автопилот` runs `capture_reference_autopilot.py`: the gestures are performed with no hand on the
  mouse. The window hides itself for the duration, because the synthetic clicks land at desktop
  coordinates and a window over the viewport would catch them instead of Maya.
* `Вручную: чек-лист пивота` walks the same steps with the buttons below - for the gestures the
  synthetic input does not reproduce.
* `Вручную: свободная запись` starts a session with no checklist at all, where anything labelled and
  captured is recorded. This is the mode a question about a tool other than the pivot starts in.

The two meet at `Доснять неудавшиеся вручную`: an automated run judges every step by what actually
moved, and the ones it reports as `ЖЕСТ НЕ СРАБОТАЛ` become a hand-driven checklist of exactly those
steps, into a file of its own so the automated artifact stays as it was recorded.

`capture_reference_gestures.py` is the session behind all of it; this only puts buttons on it. The
instruction is on screen, one button records, and the log grows next to it.

The commands Maya runs are collected by `capture_reference_commands.py` - one global sink, written
straight to a file with no UI of its own - so a record carries both where the pivot ended up and
which command put it there, and the window does not have to show a pane of Maya talking to itself.

`Записать активацию снаппинга` is independent of those three gesture modes. It runs
`capture_reference_snapping.py` and records the complete X/C/V/J/Shift-J press/repeat/release state
machine, overlapping keys, and temporary keys over Maya's persistent snap modes with one click.

`Записать снаппинг на моделях` builds a dedicated scene and drives the actual transform
manipulators against point, curve, grid, mesh-center, view-plane and step targets. It also records
object-to-object vertex alignment, pivot-only alignment, and Shift-drag duplicates snapped to the
other object. It is the numeric behavior capture: transforms, target distances, commands and
screenshots, not only mode flags. The extended run contains 55 isolated interactions, including
handles/spaces, hierarchy, Copy/Instance, complex geometry, multi-selection, cameras and
cancel/undo cleanup.

From Maya's Script Editor. The reload is not decoration: a Maya session stays open across a day of
edits to these files and `import` answers from the cache it filled this morning, which is what
"module has no attribute" for a function plainly on disk actually means. `show()` re-reads what it
drives, so only this module needs saying out loud:

  import sys, importlib
  sys.path.append(r"S:\\Clarity\\blender\\tests\\pivot_reference")
  import capture_reference_window as window
  importlib.reload(window)
  window.show()

Reloading this module while a session runs is safe: the session lives in
`capture_reference_gestures`, not here, and `show()` leaves that one alone while it is in use. To
drop a session on purpose and start from the files as they are now, `window.reload_engine()`.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

import capture_reference_autopilot as autopilot
import capture_reference_commands as commands
import capture_reference_gestures as gestures
import capture_reference_model_snapping as model_snapping
import capture_reference_snapping as snapping
from reference_backend import cmds

_WINDOW = "clarityReferenceCaptureWindow"

_UI: dict[str, str] = {}

_DEFAULT_OUTPUT = Path(__file__).parent / "fixtures" / "maya_2025_pivot_gestures"

# The three ways a capture can be made, in the order they are reached for: let the autopilot do it,
# do the same checklist by hand when it could not, and record something with no checklist at all -
# which is the mode a question about a tool other than the pivot starts in.
_AUTO = "Автопилот: пивот, без рук"
_CHECKLIST = "Вручную: чек-лист пивота"
_FREE = "Вручную: свободная запись"
_MODES = (_AUTO, _CHECKLIST, _FREE)

# Steps the last automated run could not perform. The window offers them as a hand-driven checklist,
# because "the autopilot missed three of seven" is only useful next to a way to fill those three in.
_FAILED: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------------------------
# Staleness. A Maya session outlives many edits of these files, and `import` answers from the cache
# it filled hours ago - the failure that reads as "module has no attribute" for a function that is
# plainly there on disk.
# ---------------------------------------------------------------------------------------------

def reload_engine() -> None:
    """Re-import the session modules from disk. Any session they were holding is gone with them."""
    if gestures._SESSION is not None:
        print("capture: сессия шла; перезагрузка её роняет. Начните новую.")
    importlib.reload(commands)
    importlib.reload(gestures)
    importlib.reload(autopilot)
    importlib.reload(snapping)
    importlib.reload(model_snapping)
    gestures.set_command_reader(commands.read)


def refresh_modules(force: bool = False) -> None:
    """Re-read the modules this window drives - all of them, from disk.

    A Maya session outlives many edits of these files and `import` answers from the cache it filled
    hours ago, which is the failure that reads as "module has no attribute" or "unexpected keyword
    argument" for something plainly on disk. `importlib.reload(window)` does not help by itself:
    re-executing this module's `import` lines hands back the same cached objects, so the modules
    below have to be named.

    `force` is not politeness. Without it the check below reads "a session is running, leave it
    alone" - and a session left behind by a *crashed* run looks exactly like a running one, so the
    stale module that caused the crash is the one thing the guard then protects. Everything that
    starts a session passes `force`, because it is about to replace that session anyway.
    """
    if gestures._SESSION is not None and not force:
        return
    importlib.reload(commands)
    importlib.reload(gestures)
    importlib.reload(autopilot)
    importlib.reload(snapping)
    importlib.reload(model_snapping)
    gestures.set_command_reader(commands.read)


# ---------------------------------------------------------------------------------------------
# Redraw. Every button ends here, so the window always shows the session rather than a memory of it.
# ---------------------------------------------------------------------------------------------


def _session_running() -> bool:
    return gestures._SESSION is not None


def _refresh(message: str | None = None) -> None:
    if not cmds.window(_WINDOW, exists=True):
        return

    if "snap_activation" in _UI and cmds.control(_UI["snap_activation"], exists=True):
        cmds.button(_UI["snap_activation"], edit=True, enable=not commands.running())
    if "model_snapping" in _UI and cmds.control(_UI["model_snapping"], exists=True):
        cmds.button(_UI["model_snapping"], edit=True, enable=not commands.running())

    if not _session_running():
        cmds.text(_UI["heading"], edit=True,
                  label="Сессии нет. Режим: {}".format(_mode()))
        cmds.scrollField(_UI["instruction"], edit=True, text="")
        cmds.scrollField(_UI["log"], edit=True, text="")
        if message:
            cmds.text(_UI["message"], edit=True, label=message)
        return

    step = gestures.current_step()
    index = gestures._SESSION["index"]
    total = len(gestures.steps())
    if step is not None:
        heading = "шаг {}/{}: {}".format(index + 1, total, step["name"])
        body = "{}\n\nвопрос: {}".format(
            gestures.step_text(step), str(step.get("question", "")).strip()
        )
    elif total:
        heading = "чек-лист пройден ({} шагов)".format(total)
        body = ("Все шаги записаны. Нажмите Завершить - или продолжайте записывать свободными "
                "снимками ниже.")
    else:
        heading = "сессия без чек-листа"
        body = "Чек-листа нет. Сделайте что-нибудь, назовите это ниже и нажмите Снять."
    cmds.text(_UI["heading"], edit=True, label=heading)
    cmds.scrollField(_UI["instruction"], edit=True, text=body)

    cmds.scrollField(_UI["log"], edit=True, text=gestures.log_text())
    # 0 is the end of the text, which is where the news is: a capture session runs long.
    cmds.scrollField(_UI["log"], edit=True, insertionPosition=0)
    if message:
        cmds.text(_UI["message"], edit=True, label=message)


def _guard(action: Callable[[], str | None]) -> Callable[..., None]:
    """Run a button's action and put whatever went wrong on screen instead of only in the log."""

    def run(*_args: Any) -> None:
        if not _session_running() and action not in (
            _start,
            _retry_failed,
            _run_snap_activation,
            _run_model_snapping,
        ):
            _refresh("Сессии нет. Выберите режим и нажмите кнопку справа от него.")
            return
        try:
            message = action()
        except Exception as error:  # The window must survive a bad step.
            commands.drain()
            _refresh("{}: {}".format(type(error).__name__, error))
            raise
        # Forget what the recording itself echoed: a snapshot is a few dozen queries and a print,
        # and left in the sink they would be attributed to the *next* step.
        commands.drain()
        _refresh(message)

    return run


# ---------------------------------------------------------------------------------------------
# The buttons.
# ---------------------------------------------------------------------------------------------


def _note() -> str | None:
    text = cmds.textField(_UI["note"], query=True, text=True).strip()
    return text or None


def _clear_note() -> None:
    cmds.textField(_UI["note"], edit=True, text="")


def _mode() -> str:
    if "mode" not in _UI or not cmds.control(_UI["mode"], exists=True):
        return _AUTO
    return cmds.optionMenu(_UI["mode"], query=True, value=True) or _AUTO


def _output() -> str:
    return cmds.textField(_UI["output"], query=True, text=True).strip()


def _mode_changed(*_args: Any) -> None:
    """The buttons of a mode that is not running have no business being pressable."""
    manual = _mode() != _AUTO
    for key in ("done", "skip", "again", "capture"):
        if key in _UI and cmds.control(_UI[key], exists=True):
            cmds.button(_UI[key], edit=True, enable=manual)
    if "start" in _UI and cmds.control(_UI["start"], exists=True):
        cmds.button(_UI["start"], edit=True,
                    label="Прогнать без рук" if not manual else "Старт сессии (пересоберёт сцену)")
    if "retry" in _UI and cmds.control(_UI["retry"], exists=True):
        cmds.button(_UI["retry"], edit=True, enable=bool(_FAILED))
    _refresh()


def _begin_manual(output: str, steps: list[dict[str, Any]] | None) -> str:
    refresh_modules(force=True)
    history = Path(output).with_name(Path(output).name + "_history").with_suffix(".mel")
    commands.start(history, filter_noise=cmds.checkBox(_UI["filter"], query=True, value=True))
    gestures.set_command_reader(commands.read)
    gestures.start(output, steps=steps)
    _clear_note()
    return "Сессия начата, сцена пересобрана."


def _run_autopilot(output: str) -> str:
    """Hand the mouse to the autopilot, and get out of its way while it uses it.

    Literally out of the way: the synthetic clicks land at desktop coordinates, and this window
    sitting over the viewport would catch them instead of Maya.
    """
    global _FAILED
    _FAILED = []
    refresh_modules(force=True)
    visible = cmds.window(_WINDOW, exists=True)
    if visible:
        cmds.window(_WINDOW, edit=True, visible=False)
    try:
        autopilot.run(output)
    finally:
        if visible:
            cmds.window(_WINDOW, edit=True, visible=True)

    records = gestures._SESSION["records"] if _session_running() else []
    failed = [record["step"] for record in records
              if str(record.get("verdict", "")).startswith("ЖЕСТ НЕ СРАБОТАЛ")]
    by_name = {step["name"]: step for step in gestures._STEPS}
    _FAILED = [by_name[name] for name in failed if name in by_name]
    if "retry" in _UI and cmds.control(_UI["retry"], exists=True):
        cmds.button(_UI["retry"], edit=True, enable=bool(_FAILED))
    if not failed:
        return "Прогон закончен, все шаги сработали."
    return "Прогон закончен, не сработало шагов: {} - {}".format(len(failed), ", ".join(failed))


def _start() -> str:
    output = _output()
    if not output:
        return "Сначала укажите путь вывода."
    mode = _mode()
    if mode == _AUTO:
        return _run_autopilot(output)
    return _begin_manual(output, None if mode == _CHECKLIST else [])


def _retry_failed() -> str:
    """A hand-driven session of exactly the steps the autopilot could not perform."""
    if not _FAILED:
        return "Нечего доснимать: прошлый прогон отработал целиком."
    output = _output()
    if not output:
        return "Сначала укажите путь вывода."
    # Its own file: the automated artifact stays as it was recorded, and what a hand did afterwards
    # is a separate record rather than an edit of one.
    manual_output = str(Path(output).with_name(Path(output).name + "_manual"))
    cmds.textField(_UI["output"], edit=True, text=manual_output)
    message = _begin_manual(manual_output, list(_FAILED))
    return "{} Доснимаем шагов: {}.".format(message, len(_FAILED))


def _run_snap_activation() -> str:
    """Record Maya's snap key/persistent-mode state machine without a gesture session."""
    if commands.running():
        return "Сначала завершите текущую сессию: запись снаппинга использует свой журнал команд."
    output = _output()
    if not output:
        return "Сначала укажите путь вывода."
    refresh_modules(force=True)
    source = Path(output)
    stem = source.stem
    snap_output = source.with_name(
        stem if stem.endswith("_snap_activation") else stem + "_snap_activation"
    )
    result = snapping.run(
        snap_output,
        filter_noise=cmds.checkBox(_UI["filter"], query=True, value=True),
    )
    return "Активация снаппинга: {} сценариев, записано в {}".format(
        result["scenarios"], result["json"]
    )


def _run_model_snapping() -> str:
    """Build target models and drive real snapped manipulator drags through native input."""
    if commands.running():
        return "Сначала завершите текущую сессию: тест моделей использует свой журнал команд."
    output = _output()
    if not output:
        return "Сначала укажите путь вывода."
    refresh_modules(force=True)
    source = Path(output)
    stem = source.stem
    model_output = source.with_name(
        stem if stem.endswith("_model_snapping") else stem + "_model_snapping"
    )
    visible = cmds.window(_WINDOW, exists=True)
    if visible:
        cmds.window(_WINDOW, edit=True, visible=False)
    try:
        result = model_snapping.run(
            model_output,
            filter_noise=cmds.checkBox(_UI["filter"], query=True, value=True),
        )
    finally:
        if visible:
            cmds.window(_WINDOW, edit=True, visible=True)
    message = "Снаппинг моделей: прошло {}/{}, записано в {}".format(
        result["passed"], result["tests"], result["json"]
    )
    if result.get("failed"):
        message += "; не прошли: " + ", ".join(result["failed"])
    return message


def _recorded(name: str) -> str:
    """What the record just written actually caught - said out loud, filtering included."""
    records = gestures._SESSION["records"] if _session_running() else []
    last = records[-1] if records else {}
    message = "записано {}: команд {}, изменений {}".format(
        name, len(last.get("commands") or []), len(last.get("changes") or {}))
    if commands.dropped():
        message += ", отфильтровано служебных строк: {}".format(commands.dropped())
    return message


def _done() -> str:
    step = gestures.current_step()
    if step is None:
        return "Чек-лист пройден - сделайте свободный снимок или завершите сессию."
    gestures.done(_note())
    _clear_note()
    return _recorded(step["name"])


def _skip() -> str:
    step = gestures.current_step()
    if step is None:
        return "Пропускать больше нечего."
    reason = _note() or "пропущено из окна без указания причины"
    gestures.skip(reason)
    _clear_note()
    return "пропущен {}: {}".format(step["name"], reason)


def _again() -> str:
    gestures.again()
    return "последняя запись выброшена - повторите жест"


def _capture() -> str:
    label = cmds.textField(_UI["label"], query=True, text=True).strip()
    if not label:
        return "Свободному снимку нужна метка."
    gestures.snapshot(label, _note())
    _clear_note()
    return _recorded(label)


def _finish() -> str:
    gestures.finish()
    commands.stop()
    output = Path(gestures._SESSION["output"])
    return "записано в {}".format(output.with_suffix(".log"))


def _toggle_filter(value: bool) -> None:
    commands.set_filter(value)


# ---------------------------------------------------------------------------------------------
# The layout. One column, because the order of the controls is the order of the work: what to do,
# what to say about it, the buttons that record it, and what has been recorded so far. What Maya
# echoes has no pane of its own any more - it goes to the global sink and into the records.
# ---------------------------------------------------------------------------------------------


def show() -> str:
    """Build the window and raise it. Safe to call again; it rebuilds."""
    # No window means nothing is displaying whatever session may be recorded as running, and a
    # session in that state is far more likely to be the wreckage of a crashed run than something
    # worth preserving - so this is the moment to insist on the files as they are now. With the
    # window already up, someone may be mid-session: reload only what can be reloaded safely.
    refresh_modules(force=not cmds.window(_WINDOW, exists=True))
    # A half-built window is worse than none: Maya leaves the control behind and the next `show()`
    # finds a name it cannot delete, so anything that fails while building takes the shell with it.
    if cmds.window(_WINDOW, exists=True):
        try:
            cmds.deleteUI(_WINDOW)
        except Exception as error:
            print("capture: не удалось убрать прошлое окно:", error)
    try:
        return _build()
    except Exception as error:
        print("capture: окно не собралось:", type(error).__name__, error)
        if cmds.window(_WINDOW, exists=True):
            try:
                cmds.deleteUI(_WINDOW)
            except Exception:
                pass
        raise


def _build() -> str:
    cmds.window(_WINDOW, title="Clarity reference capture", widthHeight=(820, 640))
    form = cmds.columnLayout(adjustableColumn=True, rowSpacing=4, columnAttach=("both", 6))

    cmds.text(label="Файл вывода (без расширения - рядом пишутся .json и .log)", align="left")
    _UI["output"] = cmds.textField(text=str(_DEFAULT_OUTPUT))

    # Nothing clever about the widths: `rowLayout` is picky about which of its per-column flags may
    # appear together, and a window that will not open is worse than one that is not aligned.
    cmds.rowLayout(numberOfColumns=3, adjustableColumn=3)
    _UI["mode"] = cmds.optionMenu(label="Режим", changeCommand=_mode_changed)
    for mode in _MODES:
        cmds.menuItem(label=mode)
    # An `optionMenu` parents its items as a menu, and everything after them lands inside it unless
    # the menu parent is popped explicitly.
    cmds.setParent("..", menu=True)
    _UI["filter"] = cmds.checkBox(label="Прятать служебные строки", value=True,
                                  changeCommand=_toggle_filter)
    _UI["start"] = cmds.button(label="Прогнать без рук", command=_guard(_start))
    cmds.setParent("..")

    _UI["snap_activation"] = cmds.button(
        label="Записать активацию снаппинга (X / C / V / J / Shift-J)",
        command=_guard(_run_snap_activation),
    )
    _UI["model_snapping"] = cmds.button(
        label="Записать снаппинг на моделях (заменит текущую сцену)",
        command=_guard(_run_model_snapping),
    )

    cmds.separator(style="in", height=8)
    _UI["heading"] = cmds.text(label="Сессии нет.", align="left", font="boldLabelFont")
    _UI["instruction"] = cmds.scrollField(editable=False, wordWrap=True, height=150, text="")

    cmds.text(label="Заметка к следующей записи (необязательно; пропуск без неё тоже записывается)",
              align="left")
    _UI["note"] = cmds.textField()

    cmds.rowLayout(numberOfColumns=5, columnWidth5=(130, 130, 130, 130, 220))
    _UI["done"] = cmds.button(label="Записать", command=_guard(_done))
    _UI["skip"] = cmds.button(label="Пропустить", command=_guard(_skip))
    _UI["again"] = cmds.button(label="Переснять", command=_guard(_again))
    cmds.button(label="Завершить", command=_guard(_finish))
    _UI["retry"] = cmds.button(label="Доснять неудавшиеся вручную", enable=False,
                               command=_guard(_retry_failed))
    cmds.setParent("..")

    cmds.separator(style="in", height=8)
    cmds.rowLayout(numberOfColumns=3, adjustableColumn=2, columnWidth3=(120, 400, 150))
    cmds.text(label="Свободный снимок", align="left")
    _UI["label"] = cmds.textField()
    _UI["capture"] = cmds.button(label="Снять", command=_guard(_capture))
    cmds.setParent("..")

    _UI["message"] = cmds.text(label="", align="left")

    cmds.separator(style="in", height=8)
    cmds.text(label="Записано", align="left")
    _UI["log"] = cmds.scrollField(editable=False, wordWrap=False, height=220, text="")

    cmds.setParent("..")
    cmds.showWindow(_WINDOW)

    gestures.set_command_reader(commands.read)
    # Sets the button labels and what is pressable for the mode the menu opened on, and redraws.
    _mode_changed()
    _refresh("Готово." if not _session_running() else "Сессия уже идёт.")
    return form
