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
| Object | Reset Position / Zero | pivot returns to the object-space origin | unchanged | all four pivot channels zero, folded into translate; object matrix fixed |
| Object | Reset Orientation | unchanged | custom orientation becomes invalid | object channels stay fixed |
| Object | Reset Both | Center or Zero result | custom orientation becomes invalid | position and orientation reset independently |
| Object | Bake Position | custom world point becomes object origin | unchanged | pivot channels zero; geometry and children stay fixed |
| Object | Bake Orientation | unchanged | custom world basis becomes object basis | geometry and children stay fixed |
| Object | Bake Both | both bake rules | both bake rules | geometry and children stay fixed |
| Object | Bake on a mirrored object | origin moves as the bake says | as the bake says | a vertex does not move; verified by probe, not by the matrix |
| Object | Apply object transform | the world point it was placed on | authored frame survives | channels zeroed into the geometry; the frame is a world one |
| Object | V | nearest valid point target | unchanged | current pivot itself is excluded |
| Object | C | nearest curve target | unchanged | current pivot itself is excluded |
| Object | X | constrained grid intersection | unchanged | no first-frame jump |
| Object/Component | Click component | unchanged | target component frame | the click orients only; position is what a drag and `Shift` are for |
| Object/Component | Ctrl-click | unchanged | target component frame | no selection operator is invoked |
| Object/Component | Shift-click | target or view-plane position | unchanged | empty space uses current-pivot depth |
| Object/Component | Ctrl+Shift-click | unchanged | active axis aims at target | previous secondary axis prevents flips |
| Component | Pin then change selection/object/mode | pinned world point survives | pinned frame survives | unpin recomputes from current selection |
| Object/Component | Switch Move/Rotate/Scale | unchanged | unchanged | custom manipulator state survives |
| Object | Rotate the object | unchanged | authored frame unchanged in world space | the frame is stored in world space and does not follow the object |
| Object/Component | Cancel drag | exact snapshot | exact snapshot | DNA and runtime are restored |
| Object/Component | Undo/Redo | stored state | stored state | DNA/edit data and manipulator runtime advance together |
| Object | Orientation `World` | pivot point | world axes | authored frame is not shown, nothing is written |
| Object | Orientation `Object` | pivot point | authored frame, object axes without one | authored frame is not shown, nothing is written |
| Object/Component | Enter Edit Pivot | pivot point | the tool's own mode still | entering selects nothing: the Move context stays on `2` |
| Object/Component | Aim a frame | unchanged | authored frame | this is what selects `Custom`: the context goes to `6` |
| Object/Component | Edit Pivot off | pivot point | authored frame still | `Custom` is a tool setting and stays selected |
| Object/Component | Pick a coordinate system | pivot point | that mode | `Custom` leaves, and the frame with it - `oriValid` false |
| Component | Select other components | recomputed from the selection | the tool's own mode again | the frame went with the selection it was aimed at |

The last three rows are the split between where the manipulator sits and which way it points, and
Maya keeps them apart explicitly. `Axis Orientation` on the transform tools chooses the axes -
`World` "moves in the world space coordinate system. The object is aligned to the world space
axis", `Object` "moves an object in object space coordinate system. Axis orientation includes
rotations on the object itself", and `Custom` is the one "set through custom pivot editing mode".
The pivot has no say in it: *Set a custom axis orientation* ends with "these commands only affect
axis orientation and not pivot position", and the converse holds here - the pivot decides the
position alone. `World` therefore keeps world axes over an authored pivot, and `Object` - Blender's
`Local` under the coordinate-system menu's own name - is where the authored frame is shown once the
mode is over.

While Edit Pivot is on, the answer is neither: the Rotate Tool page says "Custom axis orientation is
automatically selected when you activate custom pivot editing mode", and Maya's marking menu shows
*nothing* checked for the duration, because `Custom` is not one of the entries it offers - it is
`manipMoveContext -mode 6`, reachable from the Tool Settings and from pivot editing, not from the
menu.

The capture pins down when it is selected, and it is not on the way in.
`interactionScenarios.pivot_edit_component_frame` reads the Move context at every step: `2` after
`ctxEditMode`, `6` once `manipPivot -ori` is written, `6` still after leaving the mode, and `2` again
once another face is selected. So authoring the frame is what selects `Custom`, it survives the mode,
and when the frame dies the context returns to the value it had before - not to some neutral one.
Setting a mode by hand goes further: in `pivot_edit_selects_custom`, the step that picks `Object` comes
back with `oriValid` false, so picking a coordinate system takes the frame with it.

This fork follows all four. `Custom` lives in #ClarityToolState::orientation_custom, one flag per
transform tool, selected by the write in either pivot backend; the tool's own mode underneath is never
written, so dropping the flag reveals exactly the previous mode. It is dropped by a Reset Orientation, by
a component selection that no longer carries the frame, by an object that is no longer selected, and by
picking a coordinate system - which resets the frame as well.

Because it is not a Blender orientation, the header keeps showing the tool's own mode while `Custom` is
selected. The marking menu is the truthful reading there - nothing checked - and it is the menu Clarity
puts the coordinate systems in.

`Apply object transform` is captured, not argued about: `interactionScenarios.freeze_transformations`
in the fixture runs `makeIdentity -apply true -t 1 -r 1 -s 1` over an authored pivot and records what
Maya 2025 leaves behind. The channels go to `T=(0,0,0) R=(0,0,0) S=(1,1,1)`, `rotatePivotTranslate` and
`scalePivotTranslate` to zero, `rotatePivot` from `(-3.054, 2.731, -4.628)` to `(-3.302, -0.657,
-0.003)` - and `rotatePivotWorld` stays at `(9.25, -4.5, 6.75)`, exactly where it was. Freeze therefore
keeps the pivot on its world point and re-expresses it in the new local space; it does not send it to
the origin. The same capture shows `manipPivot -q -ori` surviving the freeze unchanged, so Maya keeps
the authored frame as well - this fork drops it instead, by request, and that row is the one deliberate
divergence here.

`Apply object transform` follows that capture. The bake sends every channel into the geometry, pivot
channels included - leaving a pivot compensation behind shifts the object by it the moment translate is
zeroed - and then puts the pivot back on the world point the user placed it on. The authored frame needs
no carrying over at all: it is stored in world space, and the bake does not change the object's world
orientation, so it comes out of the operation untouched, exactly as `manipPivot -q -ori` does in Maya.

Putting the pivot-editing state into the scene as a real named orientation - the way Blender's own custom
orientations work - was tried and reverted. The manipulator and the transform did resolve their axes
from it, and the header could name it, but the entry is scene data that the mode has to create, keep in
sync, restore around and remove again, and every route out of the mode is a route through that
bookkeeping: the toggle, the key release, a context change that ends and rebuilds the mode, a window
losing focus, a file saved mid-mode. Removing the entry sends any slot still pointing at it to `World`
(#BKE_scene_transform_orientation_remove), so one missed restore silently rewrote the user's `Object`
setting. A reported state costs nothing and cannot do that. The manipulator and the drag answer the question through one
function, #ED_clarity_pivot_orientation_owns_axes, so the arrows cannot point along one frame while
the drag runs in another - and it asks the same per-tool slot the menu writes, not the scene default,
which is a setting no transform tool reads.

The enumeration behind all of this is `manipMoveContext -mode`: "0 - Object Space, 1 - Local Space,
2 - World Space (default), 3 - Move Along Vertex Normal, 4 - Move Along Rotation Axis, 5 - Move Along
Live Object Axis, 6 - Custom Axis Orientation, 10 - Component Space". Every transform tool keeps its
own value (`manipPivot -moveToolOri / -rotateToolOri / -scaleToolOri`), and so does this fork, in the
matching `SCE_ORIENT_TRANSLATE / ROTATE / SCALE` slot.

The defaults come from the capture rather than from the pages, because the two disagree.
`fixtures/maya_2025_pivot_debug.log` reads every context's `-mode` as its tool is activated for the
first time: Move answers `2` (World), Rotate `0` and Scale `0` (both Object), while the Scale Tool page
claims World for itself. `transform_orientation_defaults_ensure` therefore seeds Move to `World` and
the other two to `Object`, switching each slot on. Every tool then answers from its own slot instead of
sharing the scene default, which is what lets the header show the tool that is actually being used;
`_transform_orientation_slot` in `space_view3d.py` picks the same slot for the dropdown, its popover
and the orientation pie. A slot that is already on is never reseeded, so a user's own choice for a tool
survives.

The bake row above is there because that log made it a question. On `bake_orientation` the world matrix
moved its translation, even though the command runs with `preserveGeometryPosition`, and the object in
the fixture hangs under a parent with negative scale - which is exactly where a compensation built from
a matrix product can go wrong. The world matrix cannot answer it: a bake is *supposed* to move the
origin. So both captures now record a world-space vertex and a world bounding box, and the comparison
refuses any step other than an explicit object transform that moves them.

For this fork the answer is in `fixtures/clarity_pivot_interaction.json`, scenario
`bake_keeps_the_geometry`: `firstVertexWorld` reads `(6.464, -6.193, 6.545)` before the aim, after
`bake_orientation` and after `bake_position` - the same three numbers, on an object whose parent scale
is `(-2, 0.75, 1.5)`. #ED_clarity_pivot_bake compensates with `inverse(world_after) * world_before` and
restores each child's world matrix, and a mirror does not disturb either: the orthonormalization pulls
the rotation out and leaves the negative determinant in the residual, which the target carries. The
bounding box is recorded but not compared - it is cached per object and recomputed lazily, so a scripted
session reads yesterday's object-space box against today's matrix and reports a move that never
happened. Maya's side of the same question needs a capture run with the probes in place.

One divergence is deliberate. In the same log, `undo` after a `clear_selection` that dropped the frame
brings the selection back and not the frame: Maya's manip pivot is tool state and stands outside undo.
This fork pushes an undo step for that reset, so the click that cleared the selection can be undone
whole. Everything else in that log is matched: entering the mode changes nothing, authoring the frame
selects `Custom`, leaving the mode changes nothing, a pinned pivot survives a selection change while an
unpinned one dies and takes `Custom` with it back to the previous mode, both resets behave as their rows
say, `bake_position` turns the pivot's world point into the object origin, and `freeze` zeroes
`rotate`, `rotateAxis`, `scale`, `shear` and `translate` while `rotatePivotWorld` does not appear in the
diff at all.

`manipPivot` is where the pivot's own state lives, and two of its flags settle rules this fork had to
argue about. `pinPivot`: "Selection changes will not reset the pivot position/orientation when a
custom pivot is set and pinning is on" - so without pinning a selection change resets what was
authored, which is why the axes go back on deselect. `pivotOriHandle`: "when true, the pivot
manipulator will show the orientation handle during editing", the option this fork exposes as Show
Orientation Handle. Position is the exception to the reset: an object's pivot position lives in its
transform channels, and the capture confirms it survives a deselect while the frame does not.

Two rows above are the ones the channels can silently disagree with, so their Maya
definitions are spelled out. A pivot move is `xform -pivots`, whose `-preserve` defaults to
on and where "the overall transformation is preserved by modifying the rotation
translation": after a move the pivot lives in `rotatePivot` *and* `rotatePivotTranslate`.
The Move Tool documents its two reset modes as "Center Pivot: resets the pivot to the
center of the object's bounding box" and "Zero Pivot: resets the pivot to the object's
origin", and the origin is only reachable by clearing the compensation as well - which is
what `xform -zeroTransformPivots` does: "reset pivot points and pivot translations without
changing the overall matrix by applying these values into the translation channel".

Dragging and clicking are two different interactions in Maya, and only one of them turns the pivot.
*Change the pivot point* lists them separately: "hold C or V and middle-drag over another object to
snap the pivot to that object's edges or vertices" moves it, while "click a component to snap and
align the pivot to the selected component" - and `Ctrl + click` for the orientation on its own - is
what aligns it. The V and C rows above are therefore position-only; turning the pivot on every
snapped update of a drag gave it a new frame each time the element under the pointer changed.

The click aligns the pivot's X axis, which is the axis Maya aligns a component with - the same one
its `Ctrl + Shift` aim uses by default, so a clicked and an aimed pivot agree. *Set a custom axis
orientation* words it as "the manipulator's X-axis aims at the selected vertex, aligns along the
selected edge, and aligns along the face normal of the selected face"; the capture above shows what
the pivot click actually does with an edge, and it is the mean normal of the two faces beside it,
not the edge direction. Where the two disagree, the capture wins.

What differs per element is only where that normal comes from. The snap search returns a face normal
for a face, a vertex normal for a point or an edge endpoint, and the line `v1 - v0` for an edge - so
an edge hit is the one case whose normal is rebuilt from the mesh before the aim
(`clarity_pivot_edge_normal_get`). A grid intersection carries no direction and leaves the
orientation alone. `transform_snap_test.cc` pins which element needs what, and the rule that a drag
carries no orientation at all.

Both reset scenarios in the fixture move the pivot before resetting, so the captured Zero
reset is a genuine move-then-zero: it starts from the non-zero pivot *and* pivot-translate
channels of `object_pivot_move` and ends with all four at zero, world matrix unchanged.
`test_fixture.py` asserts that pairing, because zeroing only the pivots leaves the pivot at
the compensation offset with no way back.

## Custom Pivot viewport capture (Maya 2025 screen recording, 471 frames at 30 fps)

Read off a recording of Custom Pivot mode, since these are the rows the JSON fixture cannot carry:

| Observation | Frames | Detail |
| --- | --- | --- |
| Component under the pointer pre-highlights | throughout | vertex, edge and face all in `239, 99, 5`; the face also gets a fill of the same colour at roughly 14% alpha over the surface |
| Highlight needs no snap key | throughout | plain hover in Custom Pivot mode is enough |
| Cursor carries a badge and a label | throughout | arrow plus a small hollow square at the tip; the square fills orange when the target is a vertex; the label `orient` sits under it while a click would align the pivot |
| Label disappears while dragging | 322-340 | during the drag the badge stays and the label is gone |
| A click aligns, it does not move | 30, 70, 122, 162, 204, 234, 358, 408, 432 | the pivot centre stays at the same screen position across every one of them |
| X takes the clicked component's normal | 162 face, 74 vertex, 34/130/240 edges | face: the face normal. vertex: the corner's normal, down and slightly right for the bottom corner, which is where the mean of its three faces points. edge: the mean of the two faces beside it - the vertical edge left X on the bisector of the two visible faces (foreshortened to a dot at the camera), the top edge on the mean of top and right, the bottom edge on the mean of right and bottom. Never along the edge |
| The other two axes turn as little as they can | 34 | clicking the vertical edge rotated the frame 45 degrees about the axis that was already along the edge, and left it there |
| A drag moves and keeps the frame | 322-340 | the pivot centre jumps from the object centre to the dragged point while all three axis directions survive unchanged |
| The old pivot ghosts during the drag | 322-340 | a grey wireframe copy stays at the position the drag started from |

Selected-object wireframe in the same capture is `32, 161, 92`, for reference.

One row of that recording disagrees with the help, and it is the row that decides what a click does.
*Change the pivot point* says "click a component to snap and align the pivot to the selected
component" and *Snap the custom pivot to a component* adds "by default, pivot position and
orientation snap to the selected component" - but the recording shows the pivot centre holding the
same screen position through nine clicks, and a second Maya 2025 capture (2026-08-02, 276 frames)
shows the same: click a face, click a vertex, click an edge, the axes turn every time and the centre
never moves. The cursor label reads `orient` throughout, which is the gesture naming itself.

The capture wins, as this file says it does. A click orients; the position is moved by a drag, or by
the `Shift + click` that "places the pivot at the cursor". `snap_position` stays on by default
because it is also the magnet a drag snaps with - it simply has no plain click left to govern.
Following the help here was a real regression: every click dragged the pivot onto the component the
user only wanted to aim at.

## The selected handle

Maya reads which manipulator handle is selected twice while a pivot is being edited, so it is state
and not a transient of the drag.

| Handle | Gesture | Result |
| --- | --- | --- |
| Centre | `Shift + click` | pivot moves to the target outright |
| X, Y or Z | `Shift + click` | "to snap the custom pivot's position along a single axis, select one of the axis handles (X, Y, Z) on the custom pivot manipulator and Shift-click a component" |
| Centre or X | `Ctrl + Shift + click` | "the custom pivot aims its X-axis at the selected component" |
| Y or Z | `Ctrl + Shift + click` | the pivot aims that axis instead |

The centre is therefore not a fourth axis, it is the absence of a constraint, which is why
`ClarityManipulatorPivotState` carries `active_axis_handle` beside `active_axis`: the middle-button
axis drag keeps using the last axis the user picked, and only the pivot rules ask whether an axis
handle is the selected one. `ED_clarity_pivot_position_axis_constrain` holds the projection rule and
`clarity_runtime_test.cc` pins it.

## Clicking outside the object

The modifiers keep their meaning when the click misses, they just reset instead of snapping.
*Reset a component's custom pivot* lists them:

| Gesture | Result |
| --- | --- |
| Click outside the object | resets position and orientation |
| `Ctrl` + click outside | "the custom pivot's orientation" alone |
| `Ctrl + Shift` + click outside | both, "to its reference frame of selected components" - the Center reset |
| At object level | position resets to "the center of the object's bounding box" |

`Shift` is the one gesture the two pages disagree about. *Reset a component's custom pivot* reads a
`Shift`-click outside as a position reset, while *Change the pivot point* - still current in 2025 -
says "Shift + click to place the pivot at the cursor". The operator follows the newer page and
places the pivot on the view plane at the current pivot's depth, which is also what row `Shift-click`
above records.

## Entering the mode

Maya binds one key to two gestures: "press and hold the D key to temporarily enter custom pivot
editing mode", released to leave it, and "press D or Insert" for a toggle that stays on. A tap is
therefore not a short hold, it is the other gesture, and only the time the key was down separates
them - which is the same question Blender's pie menus already ask, so Clarity answers it with the
same preference, `pie_tap_timeout`, instead of a constant of its own. `Insert` is toggle-only, as
documented.

Only a press that switched the mode *on* can take it back out: pressing the key while the mode is
already on is the toggle turning it off, and the release that follows must not turn it on again.
A release that never arrives - the window lost focus mid-hold - drops the hold rather than the mode,
so the worst case is a mode left on, which another press clears.
`pivot_edit_key_release_exits` holds the rule and `clarity_runtime_test.cc` pins it.

## The left button belongs to the pivot

The `Ctrl-click` row above ends with "no selection operator is invoked", and that is a statement
about the whole gesture, not only about the operator the release runs. `view3d.select` sits on the
left button *press* in the Industry Compatible keymap Clarity builds on, so a press that reaches any
keymap changes the component selection before the pivot is touched at all. Edit Pivot therefore
swallows the press in `pivot_edit_click_handle_action` and runs the operator from the release.

A plain press is the one exception: it is still offered to the gizmo map when a handle is
highlighted, because that is how a handle gets selected and a pivot drag starts. The modifier
presses are never handle picks and are claimed unconditionally - the first click leaves the pivot
under the pointer, so gating them on the highlight sent the next `Ctrl` press to `view3d.select`.
`test_clarity_pivot.pivot_click_does_not_change_the_selection` drives all four combinations through
the real event queue and asserts the selection never moves.

Every object row is exercised with a parent using non-uniform negative scale,
an `offsetParentMatrix` containing shear, signed object scale and shear, and a
child transform. Constraints intentionally remain outside this milestone.

## The gestures, measured

The `V` / `C` / `X` rows above were written from the documentation. These numbers are from
`fixtures/maya_2025_pivot_gestures.json`, recorded by `capture_reference_autopilot.py` driving the
mouse through the operating system's own input queue, with the subject framed at 424 pixels across
and every modifier confirmed in Maya's command echo before the row was trusted.

| Gesture | What Maya ran | Where the pivot ended | Reading |
| --- | --- | --- | --- |
| Drag the pivot, no modifier | `move -r 1.92 -1.08 -1.11 …scalePivot …rotatePivot` | 1.27 from the nearest edge midpoint | nothing snaps by default; a free drag leaves the pivot where the pointer let go |
| Drag with `V`, grabbed 8 px off centre | `snapMode -point 1` then `move -rpr -3.0256 -12.6453 12.5834` | **exactly `vtx[1]`, distance 0.0** | the snap puts the pivot *on* the target; the offset between the grab and the pivot is not preserved |
| Drag with `C` | `snapMode -curve 1` then `move -r -0.46 -5.00 4.21` | 1.98 from the nearest edge midpoint | the mode engages and finds nothing: a polygon edge is not a curve |
| Drag with `X` | `snapMode -grid 1` then `move -rpr 0 0 0` | the world origin, to 1e-15 | the nearest grid intersection of the ground plane, all three components |
| Drag an *axis* handle with `V` | `snapMode -point 1` then `move -r -1.4059 0 0` | X becomes -3.0256, Y and Z unchanged | the snap is projected onto the dragged axis rather than leaving it to reach the target |
| Plain click on geometry | `select -r pivotSubject` | unchanged | in Edit Pivot the plain click is an ordinary selection, and an authored orientation dies with it: `oriValid` true → false, the Move context `6` → `2` |

Two things the echo says that no channel does. The command form itself reports whether a snap found
anything - `move -rpr <world point>` is a snap onto that point, `move -r <delta>` is a free move -
except under an axis constraint, where a successful snap still comes through as `-r` with only the
dragged component changed. And a pivot drag writes the object's own `rotatePivot` and `scalePivot`
channels: `manipPivot -p` is never involved, which is why the position half of a drag survives
`file -new` in the channels while the orientation half does not.

The orientation rings of the Edit Pivot manipulator own the first 45 pixels around its centre: a
drag started 30 or 45 pixels out authored `manipPivot -o` and moved nothing at all, and the axis
arrow was only reached at 75. Authoring an orientation is a separate handle, not a side effect of
moving the pivot.

The `_drag` screenshots show why, because they are grabs of the viewport taken with the button still
down. The manipulator is three orientation rings around a small centre, with the axis arrows outside
them; the handle under the pointer is drawn yellow, so the frame says which one the drag actually
took. In `pivot_drag_vertex_snap_drag.png` the yellow mark is the centre and the manipulator is
travelling with the cursor; in `pivot_drag_axis_handle_vertex_snap_drag.png` it is the arrow, and
the manipulator has barely moved - which is the axis constraint doing its job, one frame before the
numbers say the same thing.

## The fork against those numbers

Row by row, and the evidence on each side. The fork's half is
`clarity_pivot_snap_decision_get` in `transform_snap.cc`, the inputs it is handed in
`recalcDataClarityPivot`, and the unit tests in `transform_snap_test.cc`.

| Measured in Maya | The fork | Standing |
| --- | --- | --- |
| A snapped drag puts the pivot on the target itself; a grab 8 px off centre is not preserved | `decision.position = input.target_position`, "never offset by the drag that took it there" - `PivotLandsExactlyOnTheTarget` | agrees |
| An axis handle projects the snap onto the dragged axis: only that component moves, to the target's coordinate on it | `constrained_target_position` through `t->con.applyVec`, `AConstrainedDragKeepsThePivotOnItsConstraint` | agrees |
| No target inside tolerance: the pointer keeps the pivot, `move -r` | `PivotFollowsThePointerWithoutATarget` | agrees |
| A drag never turns the pivot; only `manipPivot -o` does, from its own handle | orientation deliberately untouched in `recalcDataClarityPivot`, `ADragPlacesThePivotWithoutTurningIt` | agrees |
| `C` engages and finds nothing on a polygon mesh: an edge is not a curve | `SCE_SNAP_TO_EDGE` with `curve_targets_only`, and `snap_object_range` rejects anything that is not `OB_CURVES_LEGACY` - `CurveGridAndMeshCenterPickTheirOwnTargets` | agrees |
| Grid snap lands on a ground-plane grid intersection, all three components | not measured on this side | open |

The decision itself is therefore already what Maya does, and it is pinned. What is not pinned is the
wiring: `has_target`, `has_constraint` and `constrained_target_position` are filled from
`t->tsnap.snap_target` and `t->con` during a real drag, and no test drives a real drag to check that
they arrive correctly. The unit tests would keep passing if the drag stopped reaching them - which
is exactly the shape of the regression the trace was added for.

One row is not a divergence but an untested premise. Maya's own page says "click a component to
snap and align the pivot to it", and the capture's click landed on geometry in *object* selection
mode, where it did what a click does there: `select -r pivotSubject`, and the authored orientation
died with the selection. Whether a click aims the pivot in component mode is a question the capture
has not asked yet, and the fork's click - which aims and is swallowed so the selection never moves -
should not be judged against an answer nobody has recorded.

### One thing the axis rule cannot be tested through

`AConstrainedDragKeepsThePivotOnItsConstraint` and the `constrained_target_position` that feeds it
are correct, and Maya's number for the same gesture is recorded above - but the path is not
reachable from the viewport in this fork, so no test can drive it and no user can use it.

Measured with the manipulator centre at a known pixel and the press walked out along the screen
direction of the pivot's X axis, each drag cancelled so the next one starts from the same centre.
`pivot-drag-begin` reports which transform the press began:

| Distance from the centre | What the press starts |
| --- | --- |
| 0 - 25 px | `TFM_TRANSLATION`, and unconstrained: a drag at 22 px snapped to the whole vertex, `result == target_co == (1, -1, 1)` |
| 40 - 70 px | `TFM_TRACKBALL` |
| 85 - 100 px | `TFM_ROTATION` |
| 120 px | nothing |

So the band that would hold the axis arrows is the centre handle's, and beyond it the rotation the
Edit Pivot mode adds takes over. The comment in `gizmogroup_apply_clarity_center_style` says "the
rings Edit Pivot adds surround the translate handles instead of rearranging them", which is the
intent; the hit zones say otherwise. In Maya the same gesture reaches the arrow at 75 px and answers
`move -r -1.405948 0 0`.

That is a divergence in the manipulator, not in the snap: dragging the pivot along one axis is
something Maya offers and this fork currently does not. The test for the rule is written and
deleted - re-adding it is a dozen lines once a press on an axis arrow starts a constrained pivot
translation.

`fixtures/clarity_edit_pivot_manipulator.png` is what this fork draws in the mode, and it says why
no distance works: a yellow centre square of about 25 px, then nothing until the cyan view ring at
90, with a single short stem below the centre. Maya's `_drag` frames show three orientation rings
around a small centre and the axis arrows outside them. The arrows here are not merely hard to hit -
they are not drawn.

Two fixes were tried against a build and neither moved a pixel, so neither is the answer:

* clearing `WM_GIZMO_SELECT_BACKGROUND` on the trackball, on the theory that its filled disc claimed
  the presses. That flag only controls the depth mask while gizmos draw into the select buffer, and
  it is what lets *other* gizmos win against a background - so clearing it can only make things
  worse.
* laying the translate handles out with the rotation present in Edit Pivot -
  `gizmo_3d_translate_layout_twtype_get(use_clarity_style && !use_edit_pivot_style, ...)` - which in
  Blender's combined gizmo is what pushes the arrows outside the rings. The drawing did not change,
  so the layout is not what decides their absence.

Visibility was the third guess and it is wrong too. `BLENDER_CLARITY_GIZMO_TRACE=1` during a real
Edit Pivot session reports `refresh: twtype=3 edit_pivot=1 clarity_pivot=1 all_hidden=0` and
`draw_prepare: visible=12` - translate arrows, plane handles, centre, the three rings, the view ring
and the trackball, all of them shown. Nothing is hidden and the layout is the combined one.

So the arrows are drawn and are still unreachable, which leaves one mechanism: the select buffer.
Gizmo picking draws every gizmo into an id buffer and reads the pixel under the cursor. The
trackball is a filled disc; a Clarity axis stem is one pixel wide (`WM_gizmo_set_line_width(...,
1.0f)` in the same function). Unless the press lands exactly on that one pixel, the disc owns the
pixel and answers first, which is precisely what the walk found: translation only where the centre
handle is, trackball everywhere the arrows run.

Picking was the fourth guess and it did not move a pixel either. Upstream gives the rotate axes
`select_bias = -2.0f` only when scale and rotation share the manipulator; widening that to cover
translate and rotation - the Edit Pivot layout - changed nothing in the walk. So either the bias is
not applied to these gizmos on this path, or it is not what decides between a filled disc and a
line.

Four attempts, four builds, no movement: the background flag, the layout, the visibility, the
picking bias. Each was a plausible mechanism argued from the code and each was answered by the same
measurement. The next person should not add a fifth guess - they should instrument the pick itself.
`wm_gizmo_find_intersected_3d` and the select-buffer read in `wm_gizmo_map.cc` can report which
gizmo id won a given pixel and by what margin, and that single line of output ends this in one
build instead of four.
