# Maya pivot golden-reference captures

`capture_reference_pivot.py` records both transform channels and the standalone
`manipPivot` state from Maya 2025. The fixture deliberately includes a parent with
non-uniform negative scale, an `offsetParentMatrix` with shear, and a child object.

Generate the fixture from the repository root with:

```powershell
$env:MAYA_APP_DIR = '..\.maya-codex'
& 'C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe' `
  tests\pivot_reference\capture_reference_pivot.py `
  --output tests\maya_pivot_reference\fixtures\maya_2025_pivot_reference.json
```

`behavior_matrix.md` maps each captured action to the channel and world-space
invariants expected from Blender.

The capture covers:

- independent custom position and orientation;
- validity, pin, position-snap, orientation-snap, reset mode, and automatic bake flags;
- Center and Zero position reset;
- orientation-only and combined reset;
- position, orientation, and combined Bake Pivot;
- component selection;
- tool switching;
- object switching while pinned;
- parent/OPM/negative-scale and child-world behavior in every scenario.

`interactionScenarios` in the same fixture answers the other half of the question - not "what
did this operation leave behind" but "and what did the step after it do to that", which is what
every Edit Pivot rule is about. Each step records `capture_transform()` plus
`capture_axis_orientation()`: the per-tool coordinate system, read both as
`manipPivot -moveToolOri/-rotateToolOri/-scaleToolOri` and as the `-mode` of each tool context.
Covered:

- the axis orientation each tool starts in;
- entering custom pivot editing mode, aiming an orientation, leaving the mode, and picking a
  coordinate system afterwards - the sequence that decides whether `Custom` stays selected;
- the same with a component selection, then a different component, then no selection at all;
- an authored frame followed by an object rotation;
- `Freeze Transformations` over an authored pivot.

Those steps need a **running Maya**: a standalone session has no tool contexts, and `ctxEditMode`
- the command `D` is bound to - has nothing to toggle. Under `mayapy` they are recorded as
`{"error": ...}` so what is missing is visible in the fixture rather than absent from it. To fill
them in, run the same module from Maya's Script Editor:

```python
import sys; sys.path.append(r"S:\Clarity\blender\tests\pivot_reference")
import capture_reference_pivot as capture
capture.write(r"S:\Clarity\blender\tests\pivot_reference\fixtures\maya_2025_pivot_interaction.json")
```

Viewport-only gestures that no command performs - modifier-click component picking, V/C/X mouse
snapping - still have to be captured by calling `capture_transform()` from the Script Editor while
performing them by hand.

## Comparing the two sides

`capture_clarity_pivot.py` records this fork in the same schema and with the same step names, and
`compare_pivot_reference.py` diffs the two. A window is required for the Clarity capture, not
`--background`: the pivot operators poll for a 3D viewport.

```powershell
& '<build>/bin/blender.exe' --factory-startup `
  --python tests/pivot_reference/capture_clarity_pivot.py -- `
  --output tests/pivot_reference/fixtures/clarity_pivot_interaction.json --quit

python tests/pivot_reference/compare_pivot_reference.py `
  --maya tests/pivot_reference/fixtures/maya_2025_pivot_interaction.json `
  --clarity tests/pivot_reference/fixtures/clarity_pivot_interaction.json
```

The comparison is over decisions, not channel values: whether a pivot position is authored, whether a
frame is authored, which coordinate system the active tool resolves to, and whether an operation moved
the pivot's world point. The two transform models reach the same manipulator through different
channels on purpose, so a numeric diff there would report noise. The exit code is 1 on any divergence,
so the comparison can guard a change instead of only describing one.

Three things the fork cannot answer for from a script, and all three are covered by
`tests/python/ui_simulate/test_clarity_pivot.py`, which drives real events:

- switching the Clarity tool, which is a physical key - the resolution falls back to Move's slot,
  which is what the comparison reads;
- dropping the frame when its selection goes: that rule runs from the event dispatcher and from the
  manipulator refresh, and a scripted session with nothing selected has neither, so
  `selection_drops_frame` records the steps but cannot confirm them, while
  `pivot_frame_goes_with_the_selection` does;
- anything about the *component* pivot, which is window runtime with no RNA of its own, so Maya's
  `pivot_edit_component_frame` stays one-sided.

The component rule - a frame aimed at a component dies when another component is selected - is the one
still without a test, and the attempt is worth recording. Read through
`wm.clarity_transform_orientation`, `Custom` stayed selected after clicking a different edge, even
though Maya's log has `oriValid True -> False` and the mode back at `2` for the same pair of steps. Two
candidates, both in `pivot_component_orientation_selection_sync`: its signature is deliberately cheap -
selection counts, selection mode, active element - and a same-size swap of one edge for another only
differs in the active element, which `BMElem.select_set` does not touch (a click does); and any read of
the component pivot resyncs it through `pivot_custom_prepare_for_read`, which rewrites the stored
signature, so a resync that happens before the rule looks erases the evidence it needs. The rule holds
interactively; what is missing is a way to observe it.

The comparison being empty except for those is the goal state, not a shortfall.
