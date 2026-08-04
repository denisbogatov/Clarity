# Pivot lifecycle integration matrix

| Scenario | Automated coverage |
| --- | --- |
| Blender TRS + Custom Pivot → Save → Load | `tests/python/clarity_pivot_lifecycle.py` |
| Delete object → Undo deletion | `clarity_pivot_lifecycle.py` and `clarity_runtime_test.cc` |
| Duplicate with Custom Pivot | Linked duplicate and deep-copied pivot assertions in Python |
| Stale reference after deletion/name reuse | `clarity_runtime_test.cc` |
| Transaction rollback of root and two children | `clarity_runtime_test.cc` |
| Parent/non-uniform/negative scale | Custom Pivot BKE test and reference fixtures |
| Bake failure on a child | Transaction captures every child before mutation; C++ rollback test |
| Cancel after snapping | Exact Object/Component backend snapshots |
| Undo after autobake | Runtime payload plus serialized `ObjectCustomPivot` state |
| Fresh factory defaults | `tests/python/clarity_interaction_defaults.py` |

Window/workspace interaction cases still require a UI test harness because Blender's
headless Python runner does not create persistent View3D tool runtimes. The runtime
reference is nevertheless ID-based and is invalidated whenever it cannot be resolved
against the current `Main`.
