# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Hand-driven Maya capture: the gestures no command performs.

Everything `manipPivot` and the tool contexts can answer is already recorded by
`capture_reference_pivot.py` and read step by step in `debug_reference_pivot.py`. What is left over
are the gestures themselves - dragging the pivot manipulator with `V`, `C` or `X` held, picking a
component with a modifier click. No command reproduces those: they exist only while a hand is on the
mouse, which is why they are the last behaviors in the fork with no reference numbers at all.

This module is the notebook for them. It builds the same fixture scene as the other captures, prints
one instruction at a time, and snapshots after each, so the answer ends up as a number in a file
instead of a memory of a viewport. Every call writes the file, so a mistyped line in the Script
Editor costs one step, not the session.

From Maya's Script Editor:

  import sys; sys.path.append(r"S:\\Clarity\\blender\\tests\\pivot_reference")
  import capture_reference_gestures as gestures
  gestures.start(r"S:\\Clarity\\blender\\tests\\pivot_reference\\fixtures\\maya_2025_pivot_gestures")

  gestures.status()             # reprint what to do now
  gestures.done()               # snapshot, print what changed, move to the next step
  gestures.done("landed exactly on the vertex")   # the same, with a note in the record
  gestures.again()              # that snapshot was wrong - drop it and redo the step
  gestures.skip("no snap in this build")          # recorded as skipped, not as done
  gestures.snapshot("tried it the other way")     # record something outside the checklist
  gestures.finish()             # closing summary and the paths

`capture_reference_window.py` puts a window in front of all of that - one button per call, the
instruction and the log on screen, and the commands Maya echoed while the gesture was performed
recorded next to its numbers. Typing the calls stays available and is the same session.

`start` replaces the current scene, as every capture in this directory does. It also takes a
checklist of its own, and `[]` for no checklist at all: a session about some other tool, where the
steps are not known in advance, records everything through `snapshot()`.

The step list at the bottom is meant to be edited. Each entry is a name, the `actions` the hand
performs - one per line, numbered on screen, because a gesture is a sequence and a paragraph cannot
show where in it you are - and the question the numbers answer. A step written as a single
`instruction` string still works: its lines are its actions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import capture_reference_pivot as reference
import debug_reference_pivot as debug
from reference_backend import cmds


def _safe(description: str, function: Callable[[], Any]) -> Any:
    return reference._safe(description, function)


# ---------------------------------------------------------------------------------------------
# The snapshot. The same transform and tool state the other captures record, plus the geometry a
# snapped position has to be checked against: "the pivot moved" is not an answer, "the pivot is
# 0.0000 away from vertex 5" is.
# ---------------------------------------------------------------------------------------------


def _vertex_world_positions(shape: str) -> list[list[float]]:
    count = _safe("polyEvaluate vertex", lambda: cmds.polyEvaluate(shape, vertex=True))
    if not isinstance(count, int):
        return []
    positions = []
    for index in range(count):
        position = _safe(
            "vtx[{}]".format(index),
            lambda index=index: cmds.xform(
                "{}.vtx[{}]".format(shape, index), query=True, worldSpace=True, translation=True
            ),
        )
        positions.append(reference._json_value(position) if isinstance(position, list) else position)
    return positions


def _edge_midpoints(shape: str, vertices: list[list[float]]) -> list[dict[str, Any]]:
    count = _safe("polyEvaluate edge", lambda: cmds.polyEvaluate(shape, edge=True))
    if not isinstance(count, int):
        return []
    midpoints = []
    for index in range(count):
        pair = _safe(
            "edge {} vertices".format(index),
            lambda index=index: cmds.polyInfo(
                "{}.e[{}]".format(shape, index), edgeToVertex=True
            ),
        )
        if not isinstance(pair, list) or not pair:
            continue
        # `polyInfo` answers "EDGE 3: 2 6 Hard", and the two vertex indices are the numbers after
        # the colon. Read positionally rather than by regex: the format is fixed and the fields
        # after the pair differ between hard and soft edges.
        fields = pair[0].split(":")[-1].split()
        try:
            first, second = int(fields[0]), int(fields[1])
        except (IndexError, ValueError):
            continue
        if first >= len(vertices) or second >= len(vertices):
            continue
        a, b = vertices[first], vertices[second]
        if not (isinstance(a, list) and isinstance(b, list)):
            continue
        midpoints.append(
            {
                "edge": index,
                "vertices": [first, second],
                "midpoint": [round((a[i] + b[i]) / 2.0, 5) for i in range(3)],
            }
        )
    return midpoints


def _distance(a: Any, b: Any) -> float | None:
    if not (isinstance(a, list) and isinstance(b, list) and len(a) >= 3 and len(b) >= 3):
        return None
    return round(sum((float(a[i]) - float(b[i])) ** 2 for i in range(3)) ** 0.5, 6)


def _nearest(position: Any, candidates: list[tuple[str, Any]]) -> dict[str, Any] | None:
    """The closest of the named points, with the distance - the whole point of the capture."""
    best: dict[str, Any] | None = None
    for name, point in candidates:
        distance = _distance(position, point)
        if distance is None:
            continue
        if best is None or distance < best["distance"]:
            best = {"what": name, "at": point, "distance": distance}
    return best


def _snapshot(node: str, shape: str) -> dict[str, Any]:
    transform = reference.capture_transform(node)
    vertices = _vertex_world_positions(shape)
    edges = _edge_midpoints(shape, vertices)
    snapshot = {
        "transform": transform,
        "tool": debug._tool_state(),
        "geometry": {"vertices": vertices, "edgeMidpoints": edges},
    }

    pivot = transform.get("manipPivot", {})
    candidates: list[tuple[str, Any]] = []
    for index, vertex in enumerate(vertices):
        candidates.append(("vtx[{}]".format(index), vertex))
    for edge in edges:
        candidates.append(("e[{}] midpoint".format(edge["edge"]), edge["midpoint"]))

    # Where the manipulator actually is, which is not always where `manipPivot` is. A pivot *drag*
    # writes the object's own `rotatePivot` and `scalePivot` - that is what the echo of a real drag
    # shows - and leaves `manipPivot` invalid, so measuring only the latter answers "no authored
    # pivot to measure" about a gesture that plainly moved one. Authored position first because it
    # wins on screen when it exists; the object's own pivot otherwise.
    if pivot.get("positionValid"):
        position, source = pivot.get("position"), "manipPivot"
    else:
        position, source = transform.get("rotatePivotWorld"), "rotatePivot world"
        candidates = [entry for entry in candidates]
    snapshot["analysis"] = {
        "pivotPosition": position,
        "pivotSource": source,
        "manipPivotPosition": pivot.get("position"),
        "manipPivotPositionValid": pivot.get("positionValid"),
        "nearest": _nearest(position, candidates),
    }
    return snapshot


# ---------------------------------------------------------------------------------------------
# The session. One module-level record because the caller is a human typing into the Script Editor
# between gestures, and threading a handle through every line of that is friction with no payoff.
# ---------------------------------------------------------------------------------------------

_SESSION: dict[str, Any] | None = None

# What Maya itself ran while the hand was on the mouse. Set by whoever can answer it -
# `capture_reference_window.py` reads a `cmdScrollFieldReporter` with `echoAllCommands` on - because
# the commands behind a gesture are the other half of its behavior: the numbers say where the pivot
# ended up, the echo says which command put it there. A reader is expected to clear its source as it
# reads, so each record gets the commands of its own step and not of the whole session.
_COMMAND_READER: Callable[[], str] | None = None


def set_command_reader(reader: Callable[[], str] | None) -> None:
    global _COMMAND_READER
    _COMMAND_READER = reader


def _take_commands() -> list[str]:
    if _COMMAND_READER is None:
        return []
    text = _safe("command reader", _COMMAND_READER)
    if not isinstance(text, str):
        return []
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def _say(*values: Any) -> None:
    print(*values)


def _require() -> dict[str, Any]:
    if _SESSION is None:
        raise RuntimeError("сначала вызовите start(<путь вывода>)")
    return _SESSION


def steps() -> list[dict[str, str]]:
    """The checklist of the running session, or the default one before it starts."""
    return _SESSION["steps"] if _SESSION is not None else _STEPS


def step_actions(step: dict[str, Any]) -> list[str]:
    """A step as the separate actions it is made of.

    A gesture is a sequence - grab here, hold this, drop there, let go - and a hand reading it off a
    screen mid-gesture needs to see where it is in that sequence, which a paragraph cannot show. A
    step written as one string still works: its lines are the actions.
    """
    actions = step.get("actions")
    if actions:
        return [str(action).strip() for action in actions if str(action).strip()]
    return [line.strip() for line in str(step.get("instruction", "")).strip().splitlines()
            if line.strip()]


def step_text(step: dict[str, Any]) -> str:
    """The actions, numbered, one per line - what the window shows and the record keeps."""
    return "\n".join(
        "{}. {}".format(number, action) for number, action in enumerate(step_actions(step), 1)
    )


def current_step() -> dict[str, str] | None:
    """The step to perform now, or None when the checklist is done or empty."""
    if _SESSION is None:
        return None
    index = _SESSION["index"]
    return _SESSION["steps"][index] if index < len(_SESSION["steps"]) else None


def rebase() -> None:
    """Take the current state as the baseline, without recording anything.

    For whatever a caller does *between* steps and does not want inside the next step's difference -
    the autopilot puts the pivot back before every gesture, and without this the reset shows up in
    the record as if the gesture had done it.
    """
    if _SESSION is None:
        return
    _SESSION["previous"] = _snapshot(_SESSION["node"], _SESSION["shape"])


def log_text() -> str:
    """The readable log as it stands, for a window that wants to show it."""
    return "\n".join(_SESSION["lines"]) if _SESSION is not None else ""


def _write() -> None:
    session = _require()
    output = Path(session["output"])
    result = {
        "schema": 1,
        "mayaVersion": _safe("about version", lambda: cmds.about(version=True)),
        "apiVersion": _safe("about apiVersion", lambda: cmds.about(apiVersion=True)),
        "subject": session["node"],
        "shape": session["shape"],
        "steps": session["records"],
        "remaining": [step["name"] for step in session["steps"][session["index"]:]],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    output.with_suffix(".log").write_text("\n".join(session["lines"]) + "\n", encoding="utf-8")


def _analysis_line(record: dict[str, Any]) -> str | None:
    analysis = (record.get("state") or {}).get("analysis") or {}
    nearest = analysis.get("nearest")
    if not nearest:
        return None
    return "  пивот ({}) {} - {} до {}".format(
        analysis.get("pivotSource"), analysis.get("pivotPosition"),
        nearest["distance"], nearest["what"]
    )


def _lines_from_records(records: list[dict[str, Any]]) -> list[str]:
    """The log, rebuilt from the records.

    One source of truth on purpose: `again()` drops a record, and a log that was appended to line by
    line would keep the dropped step's numbers under the step that replaced it.
    """
    lines: list[str] = []
    for record in records:
        if "skipped" in record:
            lines.append("{}: SKIPPED {}".format(record["step"], record["skipped"]))
            continue
        lines.append(record["step"] + (" (free capture)" if record.get("adhoc") else ""))
        if record.get("note"):
            lines.append("  note: " + record["note"])
        for line in record.get("input") or []:
            lines.append("  ввод: " + line)
        if record.get("verdict"):
            lines.append("  " + record["verdict"])
        if record.get("error"):
            lines.append("  ОШИБКА: " + str(record["error"]))
        shots = record.get("screenshots") or {}
        if shots:
            for tag in ("before", "drag", "after"):
                if shots.get(tag):
                    lines.append("  скрин {}: {}".format(tag, shots[tag]))
        elif record.get("screenshot"):
            lines.append("  скрин: " + record["screenshot"])
        for command in record.get("commands") or []:
            lines.append("  cmd: " + command)
        changes = record.get("changes") or {}
        for key, change in changes.items():
            lines.append("  {} : {} -> {}".format(key, change["from"], change["to"]))
        if not changes and record["step"] != "initial":
            lines.append("  (nothing changed)")
        analysis = _analysis_line(record)
        if analysis:
            lines.append(analysis)
    return lines


def _relog() -> None:
    session = _require()
    session["lines"] = _lines_from_records(session["records"])


def _announce() -> None:
    """Print the step to perform now, or the closing summary when the list is done."""
    session = _require()
    index = session["index"]
    total = len(session["steps"])
    if not total:
        _say("")
        _say("Без чек-листа: записывайте что нужно через snapshot('метка').")
        return
    if index >= total:
        _say("")
        _say("Все {} шагов записаны. Вызовите finish().".format(total))
        return
    step = session["steps"][index]
    _say("")
    _say("--- шаг {}/{}: {}".format(index + 1, total, step["name"]))
    _say("")
    for line in step_text(step).splitlines():
        _say("    " + line)
    _say("")
    _say("  вопрос: " + str(step.get("question", "")).strip())
    _say("  затем: gestures.done()   или   gestures.skip('почему')")


def start(output: Path | str, steps: list[dict[str, str]] | None = None) -> None:
    """New scene, first instruction. Replaces whatever is open.

    `steps` takes a checklist of its own - `[]` for none at all, which is the shape to use when the
    session is about some other tool and the gestures are not known in advance: everything is then
    recorded through `snapshot()`.
    """
    global _SESSION
    node, shape, child = reference._create_scene()
    _SESSION = {
        "output": Path(output),
        "node": node,
        "shape": shape,
        "child": child,
        "steps": list(_STEPS if steps is None else steps),
        "index": 0,
        "records": [],
        "lines": [],
        "previous": None,
    }
    _take_commands()  # Drop whatever the scene build echoed: it is not a step.
    snapshot = _snapshot(node, shape)
    _SESSION["previous"] = snapshot
    _SESSION["records"].append({"step": "initial", "state": snapshot, "changes": {}})
    _relog()
    _write()
    _say("Сцена пересобрана, объект {!r}. Шагов: {}.".format(node, len(_SESSION["steps"])))
    _announce()


def status() -> None:
    """Reprint the current instruction - the Script Editor scrolls."""
    _announce()


def _record(step: dict[str, Any], note: str | None, adhoc: bool,
            extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """One snapshot, its difference from the previous one and the commands that produced it."""
    session = _require()
    commands = _take_commands()
    snapshot = _snapshot(session["node"], session["shape"])
    record: dict[str, Any] = {
        "step": step["name"],
        "state": snapshot,
        "changes": debug._difference(session["previous"], snapshot),
    }
    if adhoc:
        record["adhoc"] = True
    instruction = step_text(step)
    if instruction:
        record["instruction"] = instruction
    if step.get("question"):
        record["question"] = str(step["question"]).strip()
    if note:
        record["note"] = note
    if commands:
        record["commands"] = commands
    if extra:
        record.update(extra)
    session["records"].append(record)
    session["previous"] = snapshot
    return record


def snapshot(label: str, note: str | None = None,
             extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record where things stand right now, without touching the checklist.

    The entry point for a session that has no checklist: label what was just done, and the record
    carries the difference it made and the commands Maya ran to make it.
    """
    session = _require()
    record = _record({"name": label}, note, adhoc=True, extra=extra)
    _relog()
    _write()
    _say("записано {}: изменений {}".format(label, len(record.get("changes") or {})))
    line = _analysis_line(record)
    if line:
        _say(line.strip())
    return record


def done(note: str | None = None, extra: dict[str, Any] | None = None) -> None:
    """Snapshot after the gesture just performed, then move on."""
    session = _require()
    index = session["index"]
    if index >= len(session["steps"]):
        _say("Шаги кончились. Вызовите finish() - или snapshot('метка'), чтобы продолжить запись.")
        return
    step = session["steps"][index]

    record = _record(step, note, adhoc=False, extra=extra)
    changes = record["changes"]
    session["index"] = index + 1
    _relog()
    _write()

    analysis = record["state"].get("analysis", {})
    nearest = analysis.get("nearest")

    _say("записано {}: изменений {}".format(step["name"], len(changes)))
    if nearest:
        _say(
            "  пивот ({}) {} - {} до {}".format(
                analysis.get("pivotSource"), analysis.get("pivotPosition"),
                nearest["distance"], nearest["what"]
            )
        )
    elif analysis.get("manipPivotPositionValid") is False:
        _say("  авторской позиции пивота нет, мерить нечего")
    _announce()


def skip(reason: str) -> None:
    """Record a step as not performed, and why. The same honesty rule the other captures follow."""
    session = _require()
    index = session["index"]
    if index >= len(session["steps"]):
        _say("Пропускать больше нечего. Вызовите finish().")
        return
    step = session["steps"][index]
    session["records"].append(
        {
            "step": step["name"],
            "instruction": step_text(step),
            "question": str(step.get("question", "")).strip(),
            "skipped": reason,
        }
    )
    _take_commands()  # Whatever was echoed belongs to no step now.
    session["index"] = index + 1
    _relog()
    _write()
    _say("пропущен {}: {}".format(step["name"], reason))
    _announce()


def again() -> None:
    """Drop the last record - for a gesture that came out wrong.

    A checklist step goes back one place so it can be performed again; a free capture only
    disappears, because there is no place for it to go back to.
    """
    session = _require()
    if len(session["records"]) <= 1:
        _say("Записей ещё нет.")
        return
    dropped = session["records"].pop()
    if not dropped.get("adhoc") and session["index"] > 0:
        session["index"] -= 1
    previous = session["records"][-1]
    session["previous"] = previous.get("state") or session["previous"]
    _relog()
    _write()
    _say("запись {} выброшена, повторите жест".format(dropped.get("step")))
    _announce()


def finish() -> None:
    """Write the closing summary and say where the two files are."""
    session = _require()
    _write()
    output = Path(session["output"])
    recorded = [r for r in session["records"] if "skipped" not in r and r["step"] != "initial"]
    skipped = [r for r in session["records"] if "skipped" in r]
    remaining = session["steps"][session["index"]:]
    _say("")
    _say("записано в {} и {}".format(output.with_suffix(".json"), output.with_suffix(".log")))
    _say("  записано шагов: {}, пропущено: {}, не дошли: {}".format(
        len(recorded), len(skipped), len(remaining)))
    for step in remaining:
        _say("  не дошли: " + step["name"])


# ---------------------------------------------------------------------------------------------
# The steps. Each one is a gesture a hand performs and a question its numbers answer. Deliberately
# no vertex is named: which one was hit is read back from `analysis.nearest`, so the hand is free to
# pick whatever the viewport makes easy, and the distance is the answer either way.
#
# `instruction` and `question` are read off the screen by the hand doing the work, so they are in the
# language that hand reads. Everything a program touches - the step name, and every identifier in
# this file - stays as it is.
# ---------------------------------------------------------------------------------------------

_STEPS: list[dict[str, Any]] = [
    {
        "name": "pivot_drag_free",
        "actions": [
            "Выделите pivotSubject и включите инструмент Move.",
            "Нажмите D - включится режим редактирования пивота.",
            "Потяните пивот за центральную ручку недалеко в сторону, без модификаторов.",
            "Отпустите кнопку мыши.",
        ],
        "question": "база: свободный драг оставляет пивот там, где отпустили курсор",
    },
    {
        "name": "pivot_drag_vertex_snap",
        "actions": [
            "Оставайтесь в режиме редактирования пивота.",
            "Возьмите центральную ручку намеренно не по центру - в нескольких пикселях от середины.",
            "Зажмите V.",
            "Отпустите пивот на любой вершине pivotSubject.",
            "Отпустите кнопку мыши, затем V.",
        ],
        "question": "садится ли пивот точно на вершину или сохраняет смещение захвата",
    },
    {
        "name": "pivot_drag_edge_snap",
        "actions": [
            "Снова возьмите центральную ручку не по центру.",
            "Зажмите C.",
            "Отпустите пивот на любом ребре pivotSubject.",
            "Отпустите кнопку мыши, затем C.",
        ],
        "question": "точно ли на линии ребра и где вдоль него - середина, конец или курсор",
    },
    {
        "name": "pivot_drag_grid_snap",
        "actions": [
            "Возьмите центральную ручку.",
            "Зажмите X.",
            "Отпустите пивот на сетке в стороне от объекта.",
            "Отпустите кнопку мыши, затем X.",
        ],
        "question": "какая точка сетки выигрывает и обнуляется ли вместе с этим высота",
    },
    {
        "name": "pivot_drag_axis_handle_vertex_snap",
        "actions": [
            "Возьмите пивот за одну из ручек оси - не за центр.",
            "Зажмите V.",
            "Целясь в вершину, которая лежит в стороне от этой оси, отпустите пивот на ней.",
            "Отпустите кнопку мыши, затем V.",
        ],
        "question": "остаётся ли снап на оси драга или сходит с неё ради вершины",
    },
    {
        "name": "pivot_orientation_component_click",
        "actions": [
            "Оставайтесь в режиме редактирования пивота.",
            "Кликните по грани pivotSubject, чтобы нацелить на неё ориентацию пивота.",
            "Если обычный клик её не нацеливает - повторите с Ctrl.",
        ],
        "question": "какую ориентацию оставляет клик по компоненту - против `manipPivot -o`",
    },
    {
        "name": "origin_with_authored_pivot",
        "actions": [
            "Выйдите из режима по D, сохранив авторский пивот.",
            "Включите Move и посмотрите на объект.",
            "Отметьте в заметке, что нарисовано в собственном origin объекта.",
        ],
        "question": "где сидит origin, пока задан авторский пивот - rotatePivot против manipPivot",
    },
]
