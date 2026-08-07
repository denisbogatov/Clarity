# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compatibility boundary for the external Autodesk reference runtime.

Usable from both runtimes, because the pivot capture needs both. Channel scenarios run under
`mayapy`, which is initialized here. The interaction scenarios - the ones that ask a tool context
what its axis orientation is, or enter custom pivot editing mode - need a running Maya: those
contexts do not exist in a standalone session, so importing this from Maya's Script Editor has to
work as well.

Which runtime this is gets decided by asking a command, not by calling `initialize` and seeing what
happens: in a running Maya that call is not ours to make. `standalone` stays None there, so the
caller knows there is no session of its own to end either.
"""

import maya.cmds as cmds  # noqa: E402

try:
    cmds.about(batch=True)
except Exception:  # An uninitialized `mayapy`: the session is ours to start.
    import maya.standalone as standalone

    standalone.initialize(name="python")
else:
    standalone = None

import maya.mel as mel  # noqa: E402
