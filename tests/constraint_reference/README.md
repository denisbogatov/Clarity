# Maya 2025 constraint reference

Generate the point-constraint fixture from the repository root:

```powershell
$env:MAYA_APP_DIR = '..\.maya-codex'
& 'C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe' `
  tests\constraint_reference\capture_reference_constraints.py `
  --output tests\maya_constraint_reference\fixtures\maya_2025_constraints.json
```

The capture records the constrained object's authored state before connection, its
evaluated channels and matrices after connection, target pivots, parent matrices,
weights, offsets, maintain-offset behavior and skipped axes.
