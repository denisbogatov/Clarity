# Maya pivot golden-reference captures

`capture_maya_pivot.py` records both transform channels and the standalone
`manipPivot` state from Maya 2025. The fixture deliberately includes a parent with
non-uniform negative scale, an `offsetParentMatrix` with shear, and a child object.

Generate the fixture from the repository root with:

```powershell
$env:MAYA_APP_DIR = '..\.maya-codex'
& 'C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe' `
  tests\maya_pivot_reference\capture_maya_pivot.py `
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

Interactive viewport-only workflows such as modifier-click component picking and V/C/X
mouse snapping must be captured by running this module from Maya's Script Editor while
performing the action. Their output uses the same `capture_transform()` schema.
