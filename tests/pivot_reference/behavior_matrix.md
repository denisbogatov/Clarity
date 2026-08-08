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
| An axis handle projects the snap onto the dragged axis: only that component moves, to the target's coordinate on it | `constrained_target_position` through `t->con.applyVec`, `AConstrainedDragKeepsThePivotOnItsConstraint`, and the handle is reachable: `pivot_axis_handle_drags_the_pivot_along_one_axis` | agrees |
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

What the click reaches on this side is worth writing down, because it silently stopped reaching
vertices. A mesh vertex comes back from the snap search only as `SCE_SNAP_TO_EDGE_ENDPOINT`:
`SCE_SNAP_TO_POINT` covers loose points - curves, lattices, cameras - and `snap_edge_points` is the
one path that turns an edge hit into one of its ends. But endpoints asked for alongside edges split
every edge into `1 / (2 * modes - 1)` bands, a third at each end, so an edge could only be hovered
over its middle third. Dropping the endpoint to fix that took vertices away entirely: hovering a
corner reported the edge, the orange point marker never appeared, and a click aimed the pivot along
an edge's normal instead of the vertex's.

Both are wanted, so both queries are asked, in order: vertices alone first, where the whole edge maps
to its nearest end and the pixel tolerance is what decides whether the pointer is close enough, then
edges and faces if that missed. The second query only runs when the first found nothing.
`pivot_snap_target_query` and `clarity_pivot_click_exec` ask the same way, because the pre-highlight
and the click have to agree on the element. `pivot_click_aligns_the_pivot_to_the_clicked_vertex`
holds the vertex half - the cube's corner, whose normal is the diagonal, 45 degrees from every face
and every edge that meets it - and its edge sibling holds the other.

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
around a small centre and the axis arrows outside them. Read at the time as the arrows not being
drawn at all; measured later, they are drawn and full length, and this frame is the unreliable
witness - see "What the handles actually measure" below.

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
picking bias. Instrumenting the pick itself ended it in one build, and the answer retires all four.

With a trace in the first pass of `gizmo_find_intersected_3d`, printing every visible gizmo and what
its `test_select` answers for the pixel under the cursor, a press 45 px out along the pivot's X axis
reads:

    PICKTRACE id=0..5 type=GIZMO_GT_arrow_3d  test_select=yes draw_select=yes answer=-1 bias=0.0
    PICKTRACE id=6    type=GIZMO_GT_primitive_3d                              answer=-2 bias=2.0
    PICKTRACE id=7..11 type=GIZMO_GT_dial_3d                                  answer=-2 bias=-2.0

Every arrow answers `-1`: it does not cover that pixel. The dials win by default, not by priority -
and they already carry `bias = -2.0`, so they are stepping back exactly as intended and it changes
nothing, because there is nothing to step back for.

So the question is not picking, ordering, bias or layout. The arrows are counted as visible and are
not where the axis runs: the manipulator screenshot shows a single short stem instead of three. What
decides an arrow's reach is its length and scale in this layout - `WM_gizmo_set_scale` and the
`length` / `offset` that `gizmo_3d_setup_draw_from_twtype` writes for `MAN_AXIS_TRANS_X/Y/Z` - and
that is the one thing not yet read. Maya's arrow is a target 75 px from the centre; ours has to
become one before any of the rest matters.

### It is not the arrows

Reading the manipulator screenshot by pixel instead of by eye moves the question. The Clarity
palette is exact - `gizmo_get_axis_color` gives the axes pure `(1,0,0)`, `(0,1,0)`, `(0,0,1)` and
the view ring `(0.34, 0.86, 1.0)` - so each handle can be found by colour and measured:

| Handle | Colour | Where it is | What that makes one gizmo unit |
| --- | --- | --- | --- |
| `MAN_AXIS_ROT_C` | `(88, 218, 255)` | circle of radius 91 px about (442.5, 361) | 76 px, at `scale_basis` 1.2 |
| `MAN_AXIS_TRANS_C` | `(255, 255, 0)` | square 33 px across, same centre | 80 px, at `scale_basis` 0.2 |
| the nine axis handles | pure R / G / B | nothing at 76 - 80 px | - |

So a handle one unit long should reach about 78 px, which is Maya's 75 within the eye's tolerance,
and none of them does. There is no pure green and no pure blue pixel anywhere in the frame. The only
axis colour drawn is red, in an eight-sided ring about 11 px from the centre - an octagon is what
`imm_draw_circle_fill_3d(..., 8)` makes of an arrow head, so that is very likely one arrow head at a
fourteenth of its reach, but the count is too small to insist on.

The missing handles are `TRANS_X/Y/Z`, `TRANS_XY/YZ/ZX` and `ROT_X/Y/Z`; the drawn ones are
`TRANS_C` and `ROT_C`. Read on its own the picture says every handle that inherits the manipulator
matrix is gone and no handle that only inherits its position is - which is a clean split, and wrong.
The picture is not to be trusted: its one stem is `(237, 100, 18)`, and no handle in
`gizmo_get_axis_color` is that colour under either palette. Something is in that frame that the
manipulator does not explain, so it has to be re-taken before it is read again.

### What the handles actually measure

`gizmo_trace_dump_axes` in `transform_gizmo_3d.cc` prints, once a second per `draw_prepare` and once
per handle, everything that decides where a handle lands: hidden flag, `scale_basis`, `scale_final`,
`length`, the `matrix_offset` translation, draw options, select bias, line width, colour alpha, and
where the handle's origin and its tip fall in pixels. A real Edit Pivot session, `twtype=3`,
`clarity=1`, `pivot_style=1`, `visible=12`:

| Handle | `scale_final` | `length` | Options | Alpha | From the centre |
| --- | --- | --- | --- | --- | --- |
| `TRANS_X` / `TRANS_Y` | 0.954 | 0.800 | `STEM` | 1.00 | 13 px to 61 px |
| `TRANS_Z` | 0.954 | 0.800 | `STEM` | 1.00 | 14 px to 75 px |
| `TRANS_C` | 0.191 | - | - | 1.00 | a disc of 15 px, bias `+2` |
| `ROT_C` | 1.144 | - | - | 1.00 | a ring at 90 px, bias `-2` |
| `ROT_T` | 0.954 | - | `FILL` | 0.05 | a filled disc of 75 px, bias `-2` |
| `SCALE_*` | - | - | - | - | hidden |

Nothing is collapsed. The arrows are the full length the translate layout asks for, with their
stems, at full alpha, and `rv3d->twmat` is the identity. `TRANS_X`'s origin sits on the line from the
centre through its tip, so the walk that measured the hit bands was walking along the stem, not past
it. And the arrow's whole run, 13 to 61 px, lies inside `ROT_T`'s filled disc of 75 px.

That is the divergence, and it is geometric. The measured bands read straight off the table:
`TRANS_C` owns 0 - 25, `ROT_T` owns everything out to 75 - which is where the walk found trackball -
`ROT_C`'s ring answers at 85 - 100, and past 110 there is nothing. The arrows are buried under the
disc for their entire length.

It also voids the `PICKTRACE` above. `gizmo_find_intersected_3d` consults `wmGizmoType::test_select`
only for gizmos that have no `draw_select`; `arrow_3d` has both, so its `test_select` - the callback
documented "Selection for 2D views", which compares `matrix_final[3]` against the cursor as though
it were already in pixels - is never called on this path. Reading it by hand in a 3D view returns
`-1` whatever the arrows are doing. The select buffer, guess three, was never actually tested: what
was tested was `WM_GIZMO_SELECT_BACKGROUND`, which is the depth mask, not whether the disc claims
the pixel.

The walk itself no longer has to be done by hand. `probe_clarity_pivot_handles.walk_the_axes` in
`tests/python/ui_simulate` drives the pointer out along each pivot axis in 5 px steps and presses
nothing - a press at a distance where no handle answers becomes a click, and in Edit Pivot a click
aims the pivot, so the next reading would be taken from a centre that moved. Highlighting needs only
a motion. It marks each stop on `stderr`, where the gizmo trace is already writing, and
`read_handle_walk.py` pairs the two into the table. Handles are matched by the `gz=` pointer both
traces print: the id the select buffer uses indexes the visible gizmos of that frame, and which
handles are visible changes with the mode. It asserts nothing, so it is not registered as a test.

The obvious fix was the one Maya's own frames show - the arrows outside the rings, not under them.
`gizmogroup_apply_clarity_center_style` gives the three axis arrows the rotate-aware line range in
Edit Pivot, `0.415` to `1.415`, keeping the stem the range alone would drop. The dump confirms it
took: `TRANS_X len=1.000 offset=(0.415 0.000 0.000) opts=1`. It is kept because it is what Maya
draws, not because it fixed anything - it did not.

### The nine that never answer

The walk, eighty-four stops on three axes:

| Distance | Winner | Everything the select buffer hit |
| --- | --- | --- |
| 5 - 25 px | `TRANS_C`, by bias | `TRANS_C`, `ROT_T` |
| 30 - 75 px | `ROT_T`, nearest | `ROT_T` |
| 80 px | `ROT_T`, by bias | `ROT_C`, `ROT_T` |
| 85 - 105 px | `ROT_C`, nearest | `ROT_C` |
| 110 - 130 px | nothing | nothing |

Three handles answer, ever: `TRANS_C`, `ROT_T`, `ROT_C`. The arrows are now laid out across 32 to
111 px and appear in that buffer exactly never - and neither do the three plane handles, and neither
do `ROT_X/Y/Z`. Twelve handles are offered to the pick and nine of them are never in a hit, at any
distance, on any axis.

That is the same split the screenshot showed, on a signal that has nothing to do with drawing
colours, so the split is real even though the frame that suggested it was not to be trusted. It also
settles that the layout was never the cause: moving the arrows changed where they are and not
whether they answer.

They are certainly offered. `wm_gizmogroup_intersectable_gizmos_to_list` walks the group's gizmos in
reverse creation order, which puts the six arrows at ids 0 - 5, `TRANS_C` at 6, `ROT_C` at 7,
`ROT_Z/Y/X` at 8 - 10 and `ROT_T` at 11 - matching both the old `PICKTRACE` and the `gz=` pointers
in this run. All twelve are in the list, none is hidden, and `gizmo_draw_select_3d_loop` calls
`draw_select` on each.

So the question was what those nine draw when it does, and `drawsel:` answered it: all twelve, every
pick, `drawn=12`, each with the geometry it should have. `TRANS_X` draws itself from world
`(0.723, 0, 0)` along `(1.741, 0, 0)`, which is the layout it was given.

In pixels, from the same run:

| Handle | On screen, from the centre |
| --- | --- |
| `TRANS_X`, `TRANS_Y` | 23.6 px to 72.9 px |
| `TRANS_Z` | 28.0 px to 104.8 px |
| `ROT_T`, the trackball disc | out to about 75 px |
| `ROT_C`, the ring | about 90 px |

Two things fall out of that. The rotate-aware range did not clear the disc after all: 1.415 gizmo
units along a foreshortened world axis project to 73 px, while the disc's 1.741 units are
view-aligned and project to 75. Only `TRANS_Z`, which runs nearly straight down the screen, gets
out - and it reaches 105 px, past the disc entirely, into the band where the walk finds `ROT_C` and
`TRANS_Z` is not in the hits at all.

And the walk was on the stem. At 30, 45, 60 and 70 px along the X screen direction the cursor is
0.04 px or less from the drawn `TRANS_X` segment. The handle is drawn into the buffer, the cursor is
on it, the select line is widened by `WM_GIZMO_SELECT_BIAS` to seven logical pixels while that
buffer is drawn, and it does not answer.

That retires occlusion, ordering and bias together. Nothing is on top of `TRANS_Z` at 90 px.

What the three that answer have in common is that they are view-aligned: the final matrix of
`TRANS_C`, `ROT_C` and `ROT_T` has its Z column pointing at the camera, and every handle that fails
has its own along a world axis. Whether that is the cause or another correlation is the next
question, and the cheap way to split it is a control: the same walk with Edit Pivot off. The arrows
are the same three handles there, without the dials Edit Pivot adds. If they answer, the dials are
implicated; if they do not, Clarity's translate arrows cannot be picked at all, which is a larger
bug than this one and has an obvious suspect in the `WM_gizmo_set_line_width(axis, 1.0f)` the
Clarity style gives them. `probe_clarity_pivot_handles` now walks both, and marks which.

The first attempt at that control answered nothing and is worth recording so it is not repeated:
the `move` pass reported `drawn=0` at every stop, no `drawsel:` line and no pick at all. Outside
Edit Pivot the layout comes from the active tool, and a session that never chose one has no
manipulator to walk - Edit Pivot offers the pivot handles regardless, which is why every earlier run
looked like the manipulator was simply there. The probe now presses `W`, Clarity's Move tool, before
the first pass.

One more pair is worth holding on to while that runs. `ROT_C` and `ROT_X` are the same gizmo type
with the same draw options (`0` - Clarity draws the whole ring, so neither is filled even for
select), the same line width, and the same `-2.0` bias. `ROT_C` answers wherever its ring is drawn.
`ROT_X` never answers anywhere. The only difference between them is that `ROT_C` is turned to face
the view every frame and `ROT_X` lies in a world plane.

### The arrows are fine, and Edit Pivot takes their pixels

The control, with `W` pressed so the plain Clarity move manipulator is up - the same three arrows,
without the dials Edit Pivot adds:

| Distance | `move` | `pivot` |
| --- | --- | --- |
| 5 - 25 px | `TRANS_C` | `TRANS_C` |
| 30 - 75 px | **`TRANS_X`** | `ROT_T` |
| 80 - 105 px | nothing | `ROT_C` |

and down the Z axis, where the arrow is longest:

| Distance | `move` | `pivot` |
| --- | --- | --- |
| 15 - 35 px | `TRANS_C`, then `TRANS_XY` | `TRANS_C` |
| 40 - 105 px | **`TRANS_Z`** | `ROT_T` to 75, `ROT_C` from 85 |

So Clarity's arrows are pickable, at one pixel of line width, exactly across the span they are drawn
in - and the span is right too: `TRANS_Z` is drawn from 13 to 71 px and answers to 105, because the
select pass draws the arrow head a third of a unit longer than the stem. Line width was not the
suspect it looked like, and neither was facing the view. Turn Edit Pivot on and the same handle, at
the same pixel, is not in the hits at all.

What replaces it is whatever dial covers that pixel - `ROT_T`'s filled disc out to 75 px, `ROT_C`'s
ring beyond it - and the dials are drawn after the arrows: `wm_gizmogroup_intersectable_gizmos_to_list`
reverses creation order, so arrows take the low ids and every dial a higher one. In the `move` pass
the only handle drawn after the arrows is `TRANS_C`, which covers the centre and nothing else, and
there several handles are recorded together in one hit list. That reads as the last writer taking
the pixel, but the buffer's own bookkeeping has not been read, so treat the mechanism as inferred
and the control as measured.

The narrow fix is the one Maya's manipulator already implies: `MAN_AXIS_ROT_T` is hidden while Edit
Pivot's style is on. The mode turns the rotate layout on to get the orientation rings and the
trackball arrives with it; Maya's pivot manipulator has no such handle, and this one was swallowing
every press meant for an axis.

### Row six, closed

The walk after that change, in Edit Pivot:

| Distance | X | Y | Z |
| --- | --- | --- | --- |
| 5 - 15 px | `TRANS_C` | `TRANS_C` | `TRANS_C` |
| 20 - 35 px | `TRANS_C` | `TRANS_C` | `TRANS_XY` |
| 30 - 90 px | `TRANS_X` | `TRANS_Y` | - |
| 40 - 125 px | - | - | `TRANS_Z` |
| 95 - 105 px | `ROT_C` | `ROT_C` | - |

The axis arrows answer, across their whole drawn span, and the rings answer where the arrows do not.
The two overlap between 45 and 60 px and again at the view ring: there both are in the hit list, and
the arrow wins on the `-2.0` bias the rotate dials already carry, which is upstream's own rule for
translate and rotate sharing a manipulator. The walk only samples along the three axes, which is
exactly where the arrows are, so it says nothing about the rest of each ring's circumference - that
is untouched.

So the row moves from open to agreeing under the pointer, and
`pivot_axis_handle_drags_the_pivot_along_one_axis` presses the middle of the X arrow, cancels the
drag, and reads `pivot-drag-begin` for `mode=1` with `CON_APPLY | CON_AXIS0`. It derives the press
pixel rather than hard-coding it: the manipulator is drawn at a constant pixel size, one gizmo unit
is `gizmo_size` pixels in the view plane, the arrow spans 0.415 to 1.415 of those, and a world axis
is foreshortened by the ratio between its projected length and a view-plane vector's.

### The cold session

Open, and separate from the row above. In a session where no Clarity transform tool has ever been
chosen, the manipulator's axis arrows answer no press at all. Press `W` once and they answer from
then on - including after switching to Select, which has no manipulator of its own.

It is not the arrows and not the state they are in. Across a cold pass and a warm one the probe
reads the same gizmo objects at the same addresses, the same eleven offered to the pick, the same
geometry drawn into the select buffer, the same `twtype=3`, the same `flag=8`, and the same cursor
pixel - and zero hits against one or more. `TRANS_C` answers in both, so the pick itself is running;
only the six arrows go missing, which is why the centre handle's reach reads 5 px longer cold.

What has been ruled out, each as its own pass of `probe_clarity_pivot_handles`, each before `W`:

| Suspect | Pass | Result |
| --- | --- | --- |
| The window, 800x600 against 1280x900 | both sizes | not it - the warm passes answer in either |
| The view distance, and the world length one gizmo unit stands for | `move-view-0.5x` | not it |
| The cube's surface in the depth buffer the pick reads | `move-wire`, `pivot-cold-wire-no-floor` | not it |
| The ground plane in the same buffer | `move-no-floor`, `pivot-cold-wire-no-floor` | not it |
| The manipulator being too small to hit | `pivot-cold-gizmo-150` | not it |
| The first entry into the mode | `pivot-no-tool-again` | not it |
| Frames - ten steps of settling before the walk | every pass | not it |
| A stale region, never redrawn | `pivot-cold-redraw`, `pivot-cold-view-nudge` | not it |
| `gizmo_show_object` | `pivot-cold-show-object` | untestable: the fork syncs the flag back to the active tool within the pass |
| The Blender tool, forced to Box Select the way `clarity_blender_tool_neutralize` does | `pivot-cold-box-select` | not it |
| A Clarity tool being active at all | `pivot-cold-select-tool`, `Q` | not it |
| Clarity's Move tool, `W` | `move` | **this is the one** |

`clarity_move_tool_activate` does exactly two things: neutralize the Blender tool, and
`clarity_transform_gizmo_activate`, which sets `gizmo_show_object`, clears `V3D_GIZMO_HIDE_CONTEXT`,
sets `V3D_GIZMO_HIDE_TOOL` and tags the region. Each of those has been reproduced on its own without
effect, and `gizmo_show_object` is read in exactly two places in the tree - the twtype calculation,
which resolves to the same `3` either way, and Clarity's own tool-state matching. So the field that
tracks the fix cannot be the field that causes it.

### Where the tracing ran out

Gizmo picking does not go through `gpu_select_pick` at all. `GPU_SELECT_NEAREST_FIRST_PASS` selects
`ALGO_SAMPLE_QUERY`, so what decides a hit is an occlusion query per id: samples rasterized, nothing
else. Traced there, the same pixel 45 px out along X:

| Pass | Samples, by select id |
| --- | --- |
| `move` | `TRANS_X` 60 |
| `pivot` | `TRANS_X` 36, `ROT_Z` 24, `ROT_Y` 22 |
| `pivot-cold` | every id 0 |

Over a whole cold walk only three of the eleven ever rasterize anything - `TRANS_Z`, `TRANS_C` and
`ROT_C`. `TRANS_X` and `TRANS_Y` are zero at every stop on every axis.

Everything the draw is handed was then read at the moment of the draw, and cold matches warm on all
of it:

* the GPU state the handles are rasterized under - `depth_test=1` (always, so nothing is rejected),
  `depth_mask=1`, `scissor=(0 0 6 6)`, `viewport=(0 0 6 6)`;
* the matrix each handle draws itself with - `TRANS_X` from world `(1.160, 0, 0)` along
  `(2.795, 0, 0)`, `scale_final` 2.795;
* the projection: the stem's endpoints, put through the model, projection and viewport in force at
  that instant, land at `(-16.5, -6.7)` and `(23.4, 13.2)` cold against `(-17.0, -5.9)` and
  `(23.9, 13.7)` warm - both crossing the 6 x 6 pick viewport, entering at `y = 1.5` and `2.3`;
* what the arrow reads for itself when it draws - `style=0`, `options=1` (the stem is drawn),
  `length=1.000`, `width=1.00`, `alpha=1.00`, identical.

Identical vertices, identical state, identical projection, zero samples against thirty-six. That is
the end of what a `fprintf` can say: every input to the rasterizer has been read and they agree, so
the next step is a frame capture, not another trace. The two traces built for this last stretch - the
projected endpoints in the select loop and the arrow's own read at draw time - have been taken back
out; they answered, and they cost thousands of lines a run.

What stays is the per-handle dump in `draw_prepare`, `pick:` with the cursor and the offered count on
every call, `pick: winner`, `drawsel:`, `drawstate:`, and the occlusion samples in
`gpu_select_sample_query.cc`. Between them a session reproduces the whole finding in one run, which
is why they are still here.

`pivot_axis_handle_drags_the_pivot_along_one_axis` presses `W` before `D` for this reason, and says
so at the press. A Maya user reaches for `W` before anything else, so the test is realistic - but it
is stepping around this, not covering it, and the suite is 11 of 11 with that step in place.

All of it is temporary and comes out with the rest of `GIZMO_TRACE` - but not before this one is
closed. To reproduce the whole finding in one run:

    set BLENDER_CLARITY_GIZMO_TRACE=1
    blender --factory-startup -p 0 0 800 600 --enable-event-simulate \
        --python tests/python/ui_simulate/run_blender_setup.py -- \
        --tests probe_clarity_pivot_handles.walk_the_axes 2> gztrace.txt
    python tests/pivot_reference/read_handle_walk.py gztrace.txt
