# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Record Maya's complete snap-mode activation state machine.

The pivot gesture capture answers where a snapped drag lands.  This capture answers the earlier
question: what is enabled while X, C, V, J, or Shift-J is down, what survives when keys overlap,
and what is restored when the keys are released.  It also records temporary keys over each of the
persistent Status Line modes.

Run it from a live Maya session.  The easiest entry point is the
``Записать активацию снаппинга`` button in ``capture_reference_window.py``.  It can also be
run from the Script Editor:

  import capture_reference_snapping as snapping
  snapping.run(r"S:\\Clarity\\blender\\tests\\pivot_reference\\fixtures\\maya_2025_snap_activation")

The result is ``<path>.json``, a readable ``<path>.log``, and the unabridged Maya command history in
``<path>_history.mel``.  The current scene is not replaced.  Global snap modes, the three transform
tools' discrete-snap settings, and the current tool are restored even when a scenario fails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import capture_reference_commands as commands
import capture_reference_pivot as reference
import debug_reference_pivot as debug
from reference_backend import cmds, mel


# Every flag exposed by Maya's `snapMode` command.  Capturing settings as well as booleans makes a
# run self-describing: tolerance, edge magnets and step distance can all change what "the same"
# activation does without changing which toolbar icon is lit.
_SNAP_MODE_FLAGS = (
    "curve",
    "distanceIncrement",
    "edgeMagnet",
    "edgeMagnetTolerance",
    "grid",
    "liveFaceCenter",
    "livePoint",
    "meshCenter",
    "pixelCenter",
    "pixelSnap",
    "point",
    "tolerance",
    "useTolerance",
    "uvTolerance",
    "viewPlane",
)

_PERSISTENT_MODES = ("grid", "curve", "point", "viewPlane", "meshCenter")

# Flags differ slightly between tool contexts.  Unsupported queries are deliberately retained as
# errors rather than hidden, because that difference is part of the Maya reference.
_CONTEXT_FLAGS = {
    "move": (
        "mode",
        "snap",
        "snapRelative",
        "snapValue",
        "snapComponentsRelative",
        "snapLiveFaceCenter",
        "snapLivePoint",
        "snapPivotOri",
        "snapPivotPos",
        "xformConstraint",
    ),
    "rotate": (
        "mode",
        "snap",
        "snapRelative",
        "snapValue",
        "snapPivotOri",
        "snapPivotPos",
    ),
    "scale": (
        "mode",
        "snap",
        "snapRelative",
        "snapValue",
        "snapPivotOri",
        "snapPivotPos",
    ),
}

_CONTEXT_COMMANDS = {
    "move": cmds.manipMoveContext,
    "rotate": cmds.manipRotateContext,
    "scale": cmds.manipScaleContext,
}

_TOOL_NAMES = {"move": "Move", "rotate": "Rotate", "scale": "Scale"}

# Maya normally answers these names from its hotkey table.  The X/C/V fallbacks are the commands
# echoed by the existing Maya 2025 reference fixture.  J is intentionally not guessed: its binding
# has changed names between Maya configurations, and recording a missing binding is more useful
# than silently exercising the wrong command.
_HOTKEYS = (
    ("grid", "x", False, "SnapToGridPress", "SnapToGridRelease"),
    ("curve", "c", False, "SnapToCurvePress", "SnapToCurveRelease"),
    ("point", "v", False, "SnapToPointPress", "SnapToPointRelease"),
    ("step", "j", False, None, None),
    ("step_relative", "j", True, None, None),
)


def _safe(description: str, function: Callable[[], Any]) -> Any:
    return reference._safe(description, function)


def _json_value(value: Any) -> Any:
    return reference._json_value(value)


def _query_hotkey(key: str, shift: bool, release: bool) -> Any:
    flag = "releaseName" if release else "name"
    kwargs = {
        "query": True,
        flag: True,
    }
    if shift:
        kwargs["shiftModifier"] = True
    return _safe(
        "hotkey {}{} {}".format("Shift-" if shift else "", key.upper(), flag),
        lambda: cmds.hotkey(key, **kwargs),
    )


def _named_command_scripts() -> dict[str, str]:
    """Resolve the nameCommand objects returned by `hotkey` to the scripts they execute."""
    count = _safe("assignCommand count", lambda: cmds.assignCommand(query=True, numElements=True))
    if not isinstance(count, int):
        return {}
    result: dict[str, str] = {}
    for index in range(1, count + 1):
        name = _safe(
            "assignCommand {} name".format(index),
            lambda index=index: cmds.assignCommand(index, query=True, name=True),
        )
        if not isinstance(name, str) or not name:
            continue
        script = _safe(
            "assignCommand {} command".format(index),
            lambda index=index: cmds.assignCommand(index, query=True, command=True),
        )
        if isinstance(script, str) and script:
            result[name] = script
    return result


def _bindings() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    scripts = _named_command_scripts()
    for name, key, shift, fallback_press, fallback_release in _HOTKEYS:
        press_name = _query_hotkey(key, shift, False)
        release_name = _query_hotkey(key, shift, True)
        press = scripts.get(press_name, press_name) if isinstance(press_name, str) else press_name
        release = (
            scripts.get(release_name, release_name)
            if isinstance(release_name, str)
            else release_name
        )
        if not isinstance(press, str) or not press:
            press = fallback_press or press
        if not isinstance(release, str) or not release:
            release = fallback_release or release
        result[name] = {
            "key": key.upper(),
            "shift": shift,
            "pressNameCommand": press_name,
            "releaseNameCommand": release_name,
            "press": press,
            "release": release,
        }
    return result


def _invoke(binding: dict[str, Any], phase: str) -> Any:
    command = binding.get(phase)
    if not isinstance(command, str) or not command:
        raise RuntimeError(
            "у {} нет команды {} в таблице hotkey Maya".format(
                ("Shift-" if binding.get("shift") else "") + str(binding.get("key")), phase
            )
        )
    return mel.eval(command.rstrip(";") + ";")


def _context_state(key: str) -> dict[str, Any]:
    query = _CONTEXT_COMMANDS[key]
    attempts: dict[str, Any] = {}
    for name in reference._context_names(key):
        exists = _safe(
            "contextInfo " + name,
            lambda name=name: cmds.contextInfo(name, exists=True),
        )
        if exists is not True:
            attempts[name] = "does not exist"
            continue
        anchor = _safe(
            "{} mode".format(name),
            lambda name=name: query(name, query=True, mode=True),
        )
        if isinstance(anchor, dict) and "error" in anchor:
            attempts[name] = anchor["error"]
            continue
        values = {
            flag: _safe(
                "{} {}".format(name, flag),
                lambda flag=flag, name=name: query(name, query=True, **{flag: True}),
            )
            for flag in _CONTEXT_FLAGS[key]
        }
        return {"context": name, "values": values, "attempts": attempts}
    return {"attempts": attempts}


def _state() -> dict[str, Any]:
    return {
        "snapMode": {
            flag: _json_value(
                _safe(flag, lambda flag=flag: cmds.snapMode(query=True, **{flag: True}))
            )
            for flag in _SNAP_MODE_FLAGS
        },
        "contexts": {key: _context_state(key) for key in _CONTEXT_FLAGS},
        "currentContext": _safe("currentCtx", lambda: cmds.currentCtx()),
        "manipPivot": {
            "snapPosition": _safe(
                "manipPivot snapPos", lambda: cmds.manipPivot(query=True, snapPos=True)
            ),
            "snapOrientation": _safe(
                "manipPivot snapOri", lambda: cmds.manipPivot(query=True, snapOri=True)
            ),
        },
    }


def _set_context_flag(key: str, flag: str, value: Any) -> Any:
    command = _CONTEXT_COMMANDS[key]
    for name in reference._context_names(key):
        exists = _safe(
            "contextInfo " + name,
            lambda name=name: cmds.contextInfo(name, exists=True),
        )
        if exists is True:
            result = _safe(
                "set {} {}".format(name, flag),
                lambda name=name: command(name, edit=True, **{flag: value}),
            )
            if not (isinstance(result, dict) and "error" in result):
                return result
    return {"error": "no {} context exists".format(key)}


def _activate_tool(key: str) -> Any:
    return cmds.setToolTo(_TOOL_NAMES[key])


def _baseline(bindings: dict[str, dict[str, Any]], tool: str = "move") -> None:
    """A known start for every scenario, without leaking one scenario into the next."""
    _safe("set tool " + tool, lambda: _activate_tool(tool))
    # Release first, then force the observable values off.  A release procedure may restore state
    # saved by its matching press, so the opposite order does not establish a baseline.
    for binding in reversed(list(bindings.values())):
        _safe("baseline release", lambda binding=binding: _invoke(binding, "release"))
    for flag in _PERSISTENT_MODES:
        _safe("clear " + flag, lambda flag=flag: cmds.snapMode(**{flag: False}))
    for key in _CONTEXT_FLAGS:
        _set_context_flag(key, "snap", False)
        _set_context_flag(key, "snapRelative", False)
    _safe("restore scenario tool " + tool, lambda: _activate_tool(tool))
    commands.drain()


def _restore(original: dict[str, Any]) -> None:
    """Put back only settings this capture mutates."""
    snap_modes = original.get("snapMode", {})
    for flag in _PERSISTENT_MODES:
        value = snap_modes.get(flag)
        if isinstance(value, (bool, int)) and value in (0, 1):
            _safe(
                "restore " + flag,
                lambda flag=flag, value=value: cmds.snapMode(**{flag: bool(value)}),
            )

    contexts = original.get("contexts", {})
    for key in _CONTEXT_FLAGS:
        values = contexts.get(key, {}).get("values", {})
        for flag in ("snap", "snapRelative", "snapValue"):
            value = values.get(flag)
            if flag == "snapValue" and isinstance(value, (int, float)):
                _set_context_flag(key, flag, value)
            elif isinstance(value, (bool, int)) and value in (0, 1):
                _set_context_flag(key, flag, bool(value))
    current = original.get("currentContext")
    if isinstance(current, str) and current:
        _safe("restore current context", lambda: cmds.setToolTo(current))


def _transition(name: str, action: Callable[[], Any], previous: dict[str, Any]) -> dict[str, Any]:
    commands.drain()
    result = _safe(name, action)
    echoed = commands.read()
    filtered_count = commands.dropped()
    current = _state()
    commands.drain()  # Snapshot queries belong to the snapshot, never to the next transition.
    record: dict[str, Any] = {
        "action": name,
        "state": current,
        "changes": debug._difference(previous, current),
        "commands": echoed.splitlines() if echoed else [],
        "filteredCommandCount": filtered_count,
    }
    if isinstance(result, dict) and "error" in result:
        record["error"] = result["error"]
    return record


def _scenario(
    name: str,
    bindings: dict[str, dict[str, Any]],
    actions: list[tuple[str, Callable[[], Any]]],
    tool: str = "move",
) -> dict[str, Any]:
    _baseline(bindings, tool)
    previous = _state()
    commands.drain()
    records = [{"action": "initial", "state": previous, "changes": {}, "commands": []}]
    for action_name, action in actions:
        record = _transition(action_name, action, previous)
        records.append(record)
        previous = record["state"]
    return {"name": name, "tool": tool, "captures": records}


def _press(binding: dict[str, Any]) -> Callable[[], Any]:
    return lambda: _invoke(binding, "press")


def _release(binding: dict[str, Any]) -> Callable[[], Any]:
    return lambda: _invoke(binding, "release")


def _activation_scenarios(bindings: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []

    # One key by itself: repeats and stray releases are where momentary modes most often get stuck.
    for mode in ("grid", "curve", "point"):
        binding = bindings[mode]
        scenarios.append(
            _scenario(
                "isolated_" + mode,
                bindings,
                [
                    ("press_" + mode, _press(binding)),
                    ("repeat_press_" + mode, _press(binding)),
                    ("release_" + mode, _release(binding)),
                    ("stray_release_" + mode, _release(binding)),
                ],
            )
        )

    # J and Shift-J operate on the active transform context, so all three tools are independent
    # reference cases rather than one case assumed to generalize.
    for mode in ("step", "step_relative"):
        binding = bindings[mode]
        for tool in _CONTEXT_FLAGS:
            scenarios.append(
                _scenario(
                    "isolated_{}_{}".format(mode, tool),
                    bindings,
                    [
                        ("press_" + mode, _press(binding)),
                        ("repeat_press_" + mode, _press(binding)),
                        ("release_" + mode, _release(binding)),
                        ("stray_release_" + mode, _release(binding)),
                    ],
                    tool=tool,
                )
            )

    # Every ordered pair.  Releasing the newest key first asks whether Maya falls back to the older
    # held key; releasing the oldest first asks whether the newer one remains effective.
    temporary = ("grid", "curve", "point", "step", "step_relative")
    for first_index, first_name in enumerate(temporary):
        for second_name in temporary[first_index + 1 :]:
            first = bindings[first_name]
            second = bindings[second_name]
            for release_order, releases in (
                ("newest_first", ((second_name, second), (first_name, first))),
                ("oldest_first", ((first_name, first), (second_name, second))),
            ):
                scenarios.append(
                    _scenario(
                        "overlap_{}_{}_{}".format(first_name, second_name, release_order),
                        bindings,
                        [
                            ("press_" + first_name, _press(first)),
                            ("press_" + second_name, _press(second)),
                            ("release_" + releases[0][0], _release(releases[0][1])),
                            ("release_" + releases[1][0], _release(releases[1][1])),
                        ],
                    )
                )

    for release_order, names in (
        ("reverse_release", tuple(reversed(temporary))),
        ("same_order_release", temporary),
    ):
        actions: list[tuple[str, Callable[[], Any]]] = [
            ("press_" + name, _press(bindings[name])) for name in temporary
        ]
        actions.extend(("release_" + name, _release(bindings[name])) for name in names)
        scenarios.append(_scenario("all_temporary_" + release_order, bindings, actions))

    # Status Line modes alone, then every temporary mode over every persistent mode.  Direct
    # `snapMode` calls exercise the same Maya state the toolbar controls and are deterministic even
    # when a workspace has customized or hidden its Status Line.
    for persistent in _PERSISTENT_MODES:
        scenarios.append(
            _scenario(
                "persistent_" + persistent,
                bindings,
                [
                    (
                        "enable_" + persistent,
                        lambda persistent=persistent: cmds.snapMode(**{persistent: True}),
                    ),
                    (
                        "disable_" + persistent,
                        lambda persistent=persistent: cmds.snapMode(**{persistent: False}),
                    ),
                ],
            )
        )
        for temporary_name in temporary:
            temporary_binding = bindings[temporary_name]
            scenarios.append(
                _scenario(
                    "persistent_{}_temporary_{}".format(persistent, temporary_name),
                    bindings,
                    [
                        (
                            "enable_" + persistent,
                            lambda persistent=persistent: cmds.snapMode(**{persistent: True}),
                        ),
                        ("press_" + temporary_name, _press(temporary_binding)),
                        ("release_" + temporary_name, _release(temporary_binding)),
                        (
                            "disable_" + persistent,
                            lambda persistent=persistent: cmds.snapMode(**{persistent: False}),
                        ),
                    ],
                )
            )

    # Maya exposes these as independent booleans, while the Clarity toolbar presents one effective
    # persistent mode.  Both activation orders reveal whether Maya makes them exclusive or lets the
    # modes compose, and the release-like disable order shows what remains selected afterwards.
    for first_index, first in enumerate(_PERSISTENT_MODES):
        for second in _PERSISTENT_MODES[first_index + 1 :]:
            for order in ((first, second), (second, first)):
                scenarios.append(
                    _scenario(
                        "persistent_switch_{}_then_{}".format(order[0], order[1]),
                        bindings,
                        [
                            (
                                "enable_" + order[0],
                                lambda mode=order[0]: cmds.snapMode(**{mode: True}),
                            ),
                            (
                                "enable_" + order[1],
                                lambda mode=order[1]: cmds.snapMode(**{mode: True}),
                            ),
                            (
                                "disable_" + order[1],
                                lambda mode=order[1]: cmds.snapMode(**{mode: False}),
                            ),
                            (
                                "disable_" + order[0],
                                lambda mode=order[0]: cmds.snapMode(**{mode: False}),
                            ),
                        ],
                    )
                )

    # Maya also has a persistent discrete-snap switch in every transform tool.  Record how every
    # temporary key composes with it instead of assuming the global snapMode flags tell that story.
    for tool in _CONTEXT_FLAGS:
        for temporary_name in temporary:
            temporary_binding = bindings[temporary_name]
            scenarios.append(
                _scenario(
                    "persistent_step_{}_temporary_{}".format(tool, temporary_name),
                    bindings,
                    [
                        ("enable_step", lambda tool=tool: _set_context_flag(tool, "snap", True)),
                        ("press_" + temporary_name, _press(temporary_binding)),
                        ("release_" + temporary_name, _release(temporary_binding)),
                        ("disable_step", lambda tool=tool: _set_context_flag(tool, "snap", False)),
                    ],
                    tool=tool,
                )
            )

    return scenarios


def _log_text(result: dict[str, Any]) -> str:
    lines = [
        "Maya {} snap activation".format(result["mayaVersion"]),
        "scenarios: {}".format(len(result["scenarios"])),
        "",
        "hotkey bindings:",
    ]
    for name, binding in result["bindings"].items():
        key = ("Shift-" if binding.get("shift") else "") + str(binding.get("key"))
        lines.append(
            "  {} ({}): press={!r}, release={!r}".format(
                name, key, binding.get("press"), binding.get("release")
            )
        )

    for scenario in result["scenarios"]:
        lines.extend(("", "[{}] tool={}".format(scenario["name"], scenario["tool"])))
        for record in scenario["captures"]:
            snap = record["state"]["snapMode"]
            contexts = record["state"]["contexts"]
            active = [name for name in _PERSISTENT_MODES if snap.get(name) is True]
            context_snap = {
                key: value.get("values", {}).get("snap") for key, value in contexts.items()
            }
            lines.append(
                "  {}: snapMode={} contextSnap={} changes={} commands={}".format(
                    record["action"],
                    active or ["none"],
                    context_snap,
                    len(record.get("changes") or {}),
                    len(record.get("commands") or []),
                )
            )
            if record.get("error"):
                lines.append("    ERROR: " + str(record["error"]))
            for command in record.get("commands") or []:
                lines.append("    cmd: " + command)
            for path, change in (record.get("changes") or {}).items():
                lines.append("    {}: {} -> {}".format(path, change["from"], change["to"]))
    return "\n".join(lines) + "\n"


def run(output: Path | str, filter_noise: bool = True) -> dict[str, Any]:
    """Run every activation sequence and write the three reference artifacts."""
    output = Path(output)
    if output.suffix in (".json", ".log", ".mel"):
        output = output.with_suffix("")
    output.parent.mkdir(parents=True, exist_ok=True)
    history = output.with_name(output.name + "_history").with_suffix(".mel")

    bindings = _bindings()
    original = _state()
    if commands.running():
        raise RuntimeError(
            "уже идёт другая запись команд Maya; сначала завершите её"
        )
    commands.start(history, filter_noise=filter_noise)
    commands.drain()
    try:
        scenarios = _activation_scenarios(bindings)
        result = {
            "schema": 1,
            "mayaVersion": cmds.about(version=True),
            "apiVersion": cmds.about(apiVersion=True),
            "bindings": bindings,
            "capturedSnapModeFlags": list(_SNAP_MODE_FLAGS),
            "scenarios": scenarios,
        }
    finally:
        _restore(original)
        commands.drain()
        commands.stop()

    json_path = output.with_suffix(".json")
    log_path = output.with_suffix(".log")
    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log_path.write_text(_log_text(result), encoding="utf-8")
    print("snap activation: wrote", json_path, log_path, "and", history)
    return {
        "json": str(json_path),
        "log": str(log_path),
        "history": str(history),
        "scenarios": len(result["scenarios"]),
    }
