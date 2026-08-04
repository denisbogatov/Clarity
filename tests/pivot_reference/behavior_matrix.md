# Maya Edit Pivot behavior matrix

This matrix is the contract between the Maya 2025 captures and Blender's Maya
transform backend. Channel values come from
`fixtures/maya_2025_pivot_reference.json`; viewport-only rows use the same
`capture_transform()` schema when recorded interactively.

| Context | Action | Position | Orientation | Transform-channel invariant |
| --- | --- | --- | --- | --- |
| Object | Move pivot | rotate and scale pivots move to one world point | unchanged | object and child world matrices stay fixed |
| Object | Rotate orientation | unchanged | manipulator runtime changes | object channels stay fixed until Bake |
| Object | Reset Position / Center | hierarchy bounds center | unchanged | preserve compensation keeps geometry fixed |
| Object | Reset Position / Zero | zero rotate/scale pivot channels | unchanged | preserve compensation keeps object matrix fixed |
| Object | Reset Orientation | unchanged | custom orientation becomes invalid | object channels stay fixed |
| Object | Reset Both | Center or Zero result | custom orientation becomes invalid | position and orientation reset independently |
| Object | Bake Position | custom world point becomes object origin | unchanged | pivot channels zero; geometry and children stay fixed |
| Object | Bake Orientation | unchanged | custom world basis becomes object basis | geometry and children stay fixed |
| Object | Bake Both | both bake rules | both bake rules | geometry and children stay fixed |
| Object | V | nearest valid point target | optional target frame | current pivot itself is excluded |
| Object | C | nearest curve target | optional curve frame | current pivot itself is excluded |
| Object | X | constrained grid intersection | unchanged | no first-frame jump |
| Object/Component | Click component | target position | target component frame | position/orientation flags are independent |
| Object/Component | Ctrl-click | unchanged | target component frame | no selection operator is invoked |
| Object/Component | Shift-click | target or view-plane position | unchanged | empty space uses current-pivot depth |
| Object/Component | Ctrl+Shift-click | unchanged | active axis aims at target | previous secondary axis prevents flips |
| Component | Pin then change selection/object/mode | pinned world point survives | pinned frame survives | unpin recomputes from current selection |
| Object/Component | Switch Move/Rotate/Scale | unchanged | unchanged | custom manipulator state survives |
| Object/Component | Cancel drag | exact snapshot | exact snapshot | DNA and runtime are restored |
| Object/Component | Undo/Redo | stored state | stored state | DNA/edit data and manipulator runtime advance together |

Every object row is exercised with a parent using non-uniform negative scale,
an `offsetParentMatrix` containing shear, signed object scale and shear, and a
child transform. Constraints intentionally remain outside this milestone.
