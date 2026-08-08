# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""One global, hidden sink for the commands Maya runs, and the filter that makes it readable.

Both front ends need the same two things - what did Maya just run, and which of that was Maya
talking to itself - so they live here once rather than in a pane of a window that an automated run
never opens.

The sink is Maya's own history file, not a `cmdScrollFieldReporter`: a reporter is a control, a
control needs a layout, a layout needs a window, and an automated capture has no business opening
one. `scriptEditorInfo -writeHistory` writes the same stream to a file with no UI at all, and
reading it from the last offset gives exactly the commands of the last step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reference_backend import cmds

# ---------------------------------------------------------------------------------------------
# Noise. `echoAllCommands` means *all*, and Maya talks to itself constantly: one click on an object
# echoes forty lines of panel, layer, HUD and tool-settings refreshes around the one command that
# did something. The list below is measured from a real session of this workspace, not guessed, and
# it is a deny list rather than an allow list on purpose: a session about an unfamiliar tool is
# exactly where an unexpected command must not be hidden. Tune it freely.
# ---------------------------------------------------------------------------------------------

_NOISE_PREFIX = (
    "dR_",
    "uvTk",
    "uvTb",
    "$tmp = $g",
    "if cmds.scriptJob(",
    "cmds.scriptJob(",
    "import maya.internal",
    "import mtoa",
    "import ufe",
    "cmds.ActivateViewport20",
    "global string $g",
    "{  global string $gViewport2",
)

_NOISE_CONTAINS = (
    "ls -type materialxStack",
    "ls -type mayaUsdProxyShapeBase",
    "updateModelPanelBar",
    "refreshModelPanelMenu",
    "createModelPanelMenu",
    "createOutlinerPanelMenu",
    "buildPanelPopupMenu",
    "setRendererInModelPanel",
    "timeField -edit",
    "setFilterScript",
    "CBselectionChanged",
    "changeToolIcon",
    "findNewCurrentModelView",
    "restoreLastPanelWithFocus",
    "updatePrefsMenu",
    "updateEditorToggleCheckboxes",
    "VisibilityStateChange",
    "MTsetToggleMenuItem",
    "m341_extraHUD",
    "selectionMaskResetAll",
    "updateHyperShadePanelState",
    "updateBlendShapeEditHUD",
    "updateModelPanelBarV2Settings",
    "rebuildAnimLayerEditor",
    "updateAnimLayerEditor",
    "layerEditor",
    "AEdisablePin",
    "autoUpdateAttrEd",
    "statusLine",
    "texSelConstUpdate",
    "Unfold3DContextHotkeyScriptJob",
    "SetLastUVBrushTool",
    "textureWindowUpdate",
    "polyNormalSizeMenuUpdate",
    "resetMetadataUI",
    "makeLive -registryReset",
    "hikDefinitionFileNewCallback",
    "initGraphEditorOutliner",
    "initDopeSheetEditor",
    "initHyperGraphPanel",
    "initHyperShadePanel",
    "initVisorPanel",
    "initRelationshipPanel",
    "nodeEdInitCallback",
    "createNodeInitCallback",
    "dynPaintInitCallback",
    "InitializeNewScene",
    "buildNewSceneUI",
    "removeOldSceneUI",
    "blendShapeDeleteCurveWindow",
    "listPoseInterpolators",
    "proxyResetOptionVars",
    "preferredRenderer",
    "renameTextureViewPanel",
    "animationEditorFileCallback",
    "rendererSceneOpenedCallback",
    "removeRenderSequenceAlternateOutputFileLocation",
    "resetUnitsToDefault",
    "resetGridToDefault",
    "stopIprRendering",
    "aiViewRegionCmd",
    "clearPreFile",
    "fileCmdCallback",
    "fileCmdRestoreCallback",
    "autoSave -p",
    "evalDeferred",
    "pluginInfo",
    "memory -",
    "about -",
    "nodeType -inherited",
    "MarkingMenuPopDown",
    "popupMenu -exists tempMM",
    "cmdScrollFieldExecuter",
    "scriptEditorInfo",
    "commandEcho",
    "playblast",
    "HideHotbox",
    "hotBox -release",
    "appHome -toggleVisibility",
    # Measured from the first automated run: Maya's own bookkeeping around every gesture, and the
    # capture's own progress lines, which reach the history file like anything else printed.
    "autopilot:",
    "playbackStateChanged",
    "currentTime ",
    "nexCtx -upm",
    "updateSnapMasks",
    "scriptedPanelRunTimeCmd",
    "refresh -f;",
    "}};",
)


def is_noise(line: str) -> bool:
    text = line.strip()
    if not text:
        return True
    if text.startswith("//") or text.startswith("#"):
        # Results and comments, except the two kinds that are findings in their own right: the
        # warning about non-uniform scale and the pivot is exactly what this is here for.
        return not ("Warning" in text or "Error" in text)
    if text.startswith(_NOISE_PREFIX):
        return True
    return any(fragment in text for fragment in _NOISE_CONTAINS)


def filtered(text: str) -> tuple[str, int]:
    """The lines worth keeping, and how many were dropped - never silently."""
    lines = text.splitlines()
    kept = [line for line in lines if not is_noise(line)]
    return "\n".join(kept), len(lines) - len(kept)


# ---------------------------------------------------------------------------------------------
# The sink.
# ---------------------------------------------------------------------------------------------

_SINK: dict[str, Any] = {"path": None, "offset": 0, "filter": True, "dropped": 0, "previous": None}


def start(path: Path | str, filter_noise: bool = True) -> None:
    """Send every command Maya runs to `path`, from now on, with no UI involved."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    previous = None
    try:
        previous = cmds.scriptEditorInfo(query=True, historyFilename=True)
    except Exception:
        previous = None
    cmds.commandEcho(state=True, lineNumbers=False)
    cmds.scriptEditorInfo(historyFilename=str(path), writeHistory=True)
    _SINK.update({"path": path, "offset": 0, "filter": filter_noise, "dropped": 0,
                  "previous": previous})


def stop() -> None:
    """Stop writing, and put back the history file the session found."""
    if _SINK["path"] is None:
        return
    try:
        cmds.scriptEditorInfo(writeHistory=False)
        if _SINK["previous"]:
            cmds.scriptEditorInfo(historyFilename=_SINK["previous"])
    except Exception:
        pass
    _SINK["path"] = None


def running() -> bool:
    return _SINK["path"] is not None


def set_filter(enabled: bool) -> None:
    _SINK["filter"] = bool(enabled)


def dropped() -> int:
    """How many lines the last read filtered out."""
    return int(_SINK["dropped"])


def _text_since(offset: int) -> tuple[str, int]:
    path = _SINK["path"]
    if path is None or not Path(path).exists():
        return "", offset
    # Maya writes this file in the locale encoding, not necessarily UTF-8, and a capture running in
    # Russian reads its own progress lines back as mojibake otherwise. Offsets stay in characters,
    # which is why the whole file is decoded rather than seeked into.
    data = Path(path).read_bytes()
    for encoding in ("utf-8", "cp1251", "mbcs", "latin-1"):
        try:
            raw = data.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        raw = data.decode("utf-8", errors="replace")
    return raw[offset:], len(raw)


def peek() -> str:
    """What has been echoed since the last read, without taking it."""
    text, _ = _text_since(_SINK["offset"])
    if not _SINK["filter"]:
        return text
    kept, _ = filtered(text)
    return kept


def read() -> str:
    """Everything echoed since the last read, and move the mark past it.

    This is the shape `capture_reference_gestures.set_command_reader` expects.
    """
    text, offset = _text_since(_SINK["offset"])
    _SINK["offset"] = offset
    if not _SINK["filter"]:
        _SINK["dropped"] = 0
        return text
    kept, count = filtered(text)
    _SINK["dropped"] = count
    return kept


def drain() -> None:
    """Forget what has been echoed so far - for the capture's own queries and prints."""
    _, offset = _text_since(_SINK["offset"])
    _SINK["offset"] = offset
    _SINK["dropped"] = 0
