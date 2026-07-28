# Maya interaction behavior matrix

This matrix is the interaction-level counterpart of
`tests/maya_pivot_reference/behavior_matrix.md`. That file pins down channel and
world-matrix values; this one pins down *interaction state*: which tool stays
active, which modifier is temporary, what Cancel and Undo restore.

Every row must be executed twice: once in Maya 2025 with the fork's target
workflow, once in the fork. `Expected` is the contract; `Maya` and `Fork` are
filled in while performing the action. A row only counts as passing when the
whole line matches, not just the gizmo position.

Columns:

- **Start mode** — Object / Edit Mesh / Pose, plus selection state.
- **Tool before** — active tool when the action starts.
- **Keys** — key sequence including press/release.
- **Mouse** — mouse events, if any.
- **Selection** — selection change caused by the action.
- **Pivot** — custom pivot change caused by the action.
- **Tool after** — active tool once the action finished.
- **Snapping** — snap state during and after the action.
- **Cancel** — result of Esc / RMB cancel mid-action.
- **Undo** — result of one Undo step after the action.

`TODO` marks a cell that still has to be captured interactively. Do not delete a
`TODO` without running both applications.

## Tool lifecycle (task item 5)

| Start mode | Tool before | Keys | Mouse | Selection | Pivot | Tool after | Snapping | Cancel | Undo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Object, one object | Move | `Q` press/release | none | unchanged | unchanged | Select stays active | unchanged | n/a | tool unchanged, no undo step pushed |
| Object, one object | Select | `W` press/release | none | unchanged | unchanged | Move stays active (no one-shot operator) | unchanged | n/a | tool unchanged |
| Object, one object | Select | `E` press/release | none | unchanged | unchanged | Rotate stays active | unchanged | n/a | tool unchanged |
| Object, one object | Select | `R` press/release | none | unchanged | unchanged | Scale stays active | unchanged | n/a | tool unchanged |
| Object, one object | Move | `W` again | none | unchanged | unchanged | Move stays active, no re-entry side effect | unchanged | n/a | tool unchanged |
| Object, one object | Move (toolbar click) | none | LMB on toolbar | unchanged | unchanged | Move active, matches hotkey state | unchanged | n/a | tool unchanged |
| Object, one object | Move | none | gizmo drag, then release | unchanged | unchanged | Move still active after the transform | unchanged | transform reverted, Move still active | transform reverted, Move still active |
| Object, nothing selected | Select | `W` | none | unchanged (empty) | unchanged | Move active, no error | unchanged | n/a | TODO |
| Object, several objects | Select | `E` | none | unchanged | unchanged | Rotate active | unchanged | n/a | TODO |
| Edit Mesh | Select | `W` / `E` / `R` | none | unchanged | unchanged | matching tool active in Edit Mesh | unchanged | n/a | TODO |
| Pose | Select | `W` / `E` / `R` | none | unchanged | unchanged | matching tool active in Pose | unchanged | n/a | TODO |
| Object, Edit Pivot active | Edit Pivot | `W` | none | unchanged | unchanged | Move active, Edit Pivot ended cleanly | unchanged | n/a | TODO |
| Object, modal transform running | Move | `E` during modal | none | TODO | TODO | TODO — decide whether modal blocks the switch | TODO | TODO | TODO |

## Edit Pivot toggle (task item 6)

`D` and `Insert` are equivalent toggles, matching Maya: one press turns Edit Pivot on and it stays
on until it is toggled off. Holding a key is not part of the model.

| Start mode | Tool before | Keys | Mouse | Selection | Pivot | Tool after | Snapping | Cancel | Undo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Object, one object | Move | `D` press | none | unchanged | Edit Pivot on, pivot unchanged | Move stays active | unchanged | n/a | no undo step for entering |
| Object, Edit Pivot on | Move | `D` press again | none | unchanged | Edit Pivot off | Move stays active | unchanged | n/a | n/a |
| Object, one object | Move | `Insert` | none | unchanged | Edit Pivot on — same toggle as `D` | Move stays active | unchanged | n/a | n/a |
| Object, Edit Pivot on | Move | `Insert` | none | unchanged | Edit Pivot off | Move stays active | unchanged | n/a | n/a |
| Object, Edit Pivot on | Move | `Esc` | none | unchanged | Edit Pivot off | Move stays active | unchanged | n/a | n/a |
| Object, Edit Pivot on | Move | `D` held down (key repeat) | none | unchanged | stays on — repeats must not flip the mode | Move stays active | unchanged | n/a | n/a |
| Object, Edit Pivot on | Move | switch window and back | none | unchanged | TODO — record whether Maya keeps the mode across focus loss | Move stays active | unchanged | n/a | n/a |
| Object, Edit Pivot on | Move | object deleted | none | object gone | Edit Pivot off, no stale object reference | Move stays active | unchanged | n/a | deletion undone, Edit Pivot still off |
| Object, Edit Pivot on | Move | `Ctrl+Z` | none | TODO | TODO | Move stays active | unchanged | n/a | TODO |
| Object → Edit Mesh, Edit Pivot on | Move | `Tab` | none | unchanged | switches to the component pivot | Move stays active | unchanged | n/a | TODO |
| Object, Edit Pivot on | Move | `W` / `E` / `R` | none | unchanged | stays on, rebuilt for the new tool | new tool active | unchanged | n/a | TODO |
| Object, Edit Pivot on | Move | `X` / `C` / `V` hold | LMB drag | unchanged | pivot snapped to grid / curve / vertex | Move stays active | temporary snap only while the key is held | pivot restored, snap off | pivot restored |
| Object, Edit Pivot on | Move | none | LMB click outside 3D View | unchanged | TODO — record Maya's behavior | Move stays active | unchanged | n/a | n/a |

## Temporary snapping (task item 7)

| Start mode | Tool before | Keys | Mouse | Selection | Pivot | Tool after | Snapping | Cancel | Undo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Object, one object | Move | `X` hold | gizmo drag | unchanged | unchanged | Move | grid snap while held, scene snap settings unchanged after release | transform reverted, snap off | transform reverted |
| Object, one object | Move | `C` hold | gizmo drag | unchanged | unchanged | Move | curve snap while held | as above | as above |
| Object, one object | Move | `V` hold | gizmo drag | unchanged | unchanged | Move | vertex snap while held | as above | as above |
| Object, one object | Move | `G`, then `V` hold | mouse move | unchanged | unchanged | Move | vertex snap while held | transform reverted | transform reverted |
| Edit Mesh | Move | `V` hold | gizmo drag | unchanged | unchanged | Move | vertex snap while held | as above | as above |
| Object, Edit Pivot | Edit Pivot | `V` hold | LMB drag | unchanged | pivot snapped to vertex | Edit Pivot | vertex snap while held | pivot restored | pivot restored |
| Object, one object | Rotate / Scale | `X` / `C` / `V` hold | gizmo drag | unchanged | unchanged | Rotate / Scale | out of scope until the Maya reference is captured — must not be guessed | n/a | n/a |

## Navigation (task item 8)

| Start mode | Tool before | Keys | Mouse | Selection | Pivot | Tool after | Snapping | Cancel | Undo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Object | any | `Alt` hold | LMB drag | unchanged | unchanged | unchanged | unchanged | view restored on cancel | no undo step |
| Object | any | `Alt` hold | MMB drag | unchanged | unchanged | unchanged | unchanged | as above | no undo step |
| Object | any | `Alt` hold | RMB drag | unchanged | unchanged | unchanged | unchanged | as above | no undo step |
| Object | any | `Alt` hold | click without drag | unchanged | unchanged | unchanged | unchanged | nothing happens, no selection change | no undo step |
| Object | any | `Alt` hold | drag starting on a gizmo | unchanged | unchanged | unchanged | unchanged | navigation wins over gizmo drag — record which one Maya picks | no undo step |
| Object | any | `Alt` hold | drag leaving the window | unchanged | unchanged | unchanged | unchanged | navigation ends safely | no undo step |
| Any non-3D-View editor | any | `Alt` + editor shortcut | none | unchanged | unchanged | unchanged | unchanged | editor shortcut must still work | n/a |
| Text field / menu search focused | any | `Alt` + key | none | unchanged | unchanged | unchanged | unchanged | text editing must not be intercepted | n/a |
| Object, Blender preset selected mid-session | any | `Alt` drag | LMB | unchanged | unchanged | unchanged | unchanged | standard Blender behavior returns immediately | n/a |

Also record: tablet input, emulated three-button mouse, camera view, orthographic
and perspective view, two Blender windows, two 3D View areas.

## Selection parity (task item 9)

| Start mode | Tool before | Keys | Mouse | Selection | Pivot | Tool after | Snapping | Cancel | Undo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Object | Select | none | LMB on object | replaces selection | unchanged | Select | unchanged | n/a | previous selection restored |
| Object | Select | none | LMB on empty space | clears selection | unchanged | Select | unchanged | n/a | previous selection restored |
| Object | Select | `Shift` | LMB on object | TODO — add or toggle, must match Maya | unchanged | Select | unchanged | n/a | TODO |
| Object | Select | `Ctrl` | LMB on object | TODO — remove or toggle | unchanged | Select | unchanged | n/a | TODO |
| Object | Select | none | LMB drag marquee | replaces selection | unchanged | Select | unchanged | marquee cancelled, selection unchanged | previous selection restored |
| Object | Select | `Shift` | LMB drag marquee | TODO | unchanged | Select | unchanged | TODO | TODO |
| Object | Select | `Ctrl` | LMB drag marquee | TODO | unchanged | Select | unchanged | TODO | TODO |
| Object | Select | none | LMB on already selected object | selection unchanged | unchanged | Select | unchanged | n/a | no undo step |
| Object | Select | none | LMB through geometry (occluded object) | TODO — front-most only or through | unchanged | Select | unchanged | n/a | TODO |
| Edit Mesh | Select | none | LMB on component | replaces component selection | unchanged | Select | unchanged | n/a | previous selection restored |
| Object, Edit Pivot | Edit Pivot | none | LMB in the viewport | **unchanged** — the pivot click operator consumes the event | pivot moves to the clicked point | Edit Pivot | unchanged | pivot restored | pivot restored |

The last row is the double-event guard: a pivot click must never also change the
selection.

## Pivot usage (task items 3, 4, 10, 12)

| Start mode | Tool before | Keys | Mouse | Selection | Pivot | Tool after | Snapping | Cancel | Undo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Object, rotate pivot valid only | Rotate | `E` | gizmo drag | unchanged | unchanged | Rotate | unchanged | rotation reverted | rotation reverted |
| Object, rotate pivot valid only | Scale | `R` | gizmo drag | unchanged | unchanged | Scale | unchanged | scaling around the standard Blender pivot point, **not** the local zero | as above |
| Object, scale pivot valid only | Scale | `R` | gizmo drag | unchanged | unchanged | Scale | unchanged | scaling around the custom scale pivot | as above |
| Object, both pivots valid | Move | `W` | gizmo drag | unchanged | unchanged | Move | unchanged | translation unaffected by the custom pivot | as above |
| Object, two objects, active one has a pivot | Rotate | `E` | gizmo drag | unchanged | unchanged | Rotate | unchanged | active object's pivot is the shared center | as above |
| Object, two objects with different pivots | Rotate | `E` | gizmo drag | unchanged | unchanged | Rotate | unchanged | active object's pivot is the shared center | as above |
| Object, pivot point = Individual Origins | Rotate | `E` | gizmo drag | unchanged | unchanged | Rotate | unchanged | standard Blender Individual Origins, no custom pivot override | as above |
| Object, Blender interaction preset | Rotate | `E` | gizmo drag | unchanged | unchanged | Rotate | unchanged | standard Blender pivot point, stored custom pivot untouched | as above |
| Object, mirrored object (negative scale) | Edit Pivot | `D` hold | orientation drag | unchanged | orientation must not flip by 180° between two identical entries | previous tool | unchanged | orientation restored | orientation restored |
| Object, pinned component pivot | Edit Pivot | `Insert` | select another object | new selection | pinned pivot stays in place | Edit Pivot | unchanged | TODO | TODO |
| Object | Edit Pivot | Reset Position | none | unchanged | both rotate and scale pivots reset, both flags cleared | Edit Pivot | unchanged | TODO | pivot restored |
| Object | Edit Pivot | Reset Orientation | none | unchanged | orientation cleared, positions kept | Edit Pivot | unchanged | TODO | pivot restored |
| Object | Edit Pivot | Bake Pivot | none | unchanged | origin moves onto the rotate pivot, pivot channels cleared, world matrix of object and children preserved | Edit Pivot | unchanged | bake reverted | bake reverted |
| Object with a Blender constraint | Edit Pivot | Bake Pivot | none | unchanged | bake stays disabled, tooltip states the reason | Edit Pivot | unchanged | n/a | n/a |
