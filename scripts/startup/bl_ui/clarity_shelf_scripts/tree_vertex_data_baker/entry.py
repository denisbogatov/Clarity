"""Shelf entry point for the Tree Vertex Data Baker tool.

Point a shelf button's "Python File" at this file, not at `baker.py` directly.
The shelf runner adds this file's own directory to `sys.path` for the
duration of the call and forgets whatever it imported from here afterwards
(see `_clarity_shelf_run_script` in space_topbar.py), so `import baker`
resolves to the sibling module below and picks up edits on the next click.
Add further submodules or subfolders next to `baker.py` the same way an
addon package would, and import them from here or from `baker.py` itself.

`register()` only makes the tool's panels and operators known; the window
itself is opened by `show()`, which reuses an already-open one rather than
stacking a second copy.
"""

import baker

baker.register()
baker.TreeVDBToolWindow.show()
