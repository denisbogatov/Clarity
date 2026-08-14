# Maya Soft Selection reference oracle

This harness records Maya itself rather than reproducing Maya math in a test. It samples all nine
factory ramp presets with `gradientControlNoAttr(valueAtPoint)` and reads geometric influence from
`MGlobal.getRichSelection()` for Volume, Surface, Global, world-space scale, disconnected shells,
folded topology, multiple selected sources, and vertex/edge/face selections. It also records
`enableFalseColor` and the native `softSelectColorCurve`, then checks Maya's factory
black-to-red-to-yellow weight ramp.

## Run in Maya

Open Maya's Python Script Editor and execute (adjust the repository path if needed):

```python
import importlib
import sys

path = r"/Users/denisbogatov/Documents/DCC/Clarity/tests/soft_selection_reference"
if path not in sys.path:
    sys.path.insert(0, path)
import capture_reference_soft_selection
importlib.reload(capture_reference_soft_selection)
capture_reference_soft_selection.show()
```

Press **ПРОВЕРИТЬ ВСЁ И СОХРАНИТЬ ЭТАЛОН**. The harness makes a temporary `.mb` copy of the
current in-memory scene, runs isolated reference scenes, restores the original name and modified
state, and writes `fixtures/maya_soft_selection_reference.json`. It never overwrites the original
scene file. Opening the temporary scene clears Maya's undo history; the confirmation dialog calls
this out before the run.

The window reports PASS/FAIL. A partial JSON with a traceback is still written when a scenario
fails, which makes API/version issues diagnosable without rerunning blindly.

## Validate outside Maya

After a successful capture:

```sh
python3 tests/soft_selection_reference/validate_reference_soft_selection.py \
  tests/soft_selection_reference/fixtures/maya_soft_selection_reference.json
```

The committed C++ unit tests own deterministic ramp edge cases. The Blender integration test
`clarity_soft_selection` owns the end-to-end transform path. The captured Maya JSON is the external
oracle used to tune the prototype, especially Spline interpolation, the viewport false-color ramp,
and version-specific behavior.
