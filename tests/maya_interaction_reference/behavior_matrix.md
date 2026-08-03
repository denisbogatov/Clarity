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
| Object, Edit Pivot on | Move | switch window and back | none | unchanged | Edit Pivot stays on; transient snap and hover state is cleared; TODO — verify Maya 2025 parity | Move stays active | temporary snapping is released | n/a | n/a |
| Object, Edit Pivot dragging | Move | `D` / `Insert` press | finish or cancel the running LMB drag | unchanged | current drag owns its tail, then Edit Pivot turns off (`exit_after_drag`) | Move stays active | unchanged | pivot restored, then Edit Pivot turns off | TODO |
| Object, Edit Pivot dragging | Move | switch window during drag | LMB drag interrupted by focus loss | unchanged | Edit Pivot stays requested and the manipulator is rebuilt after the transform tail (`restart_after_drag`); TODO — verify Maya 2025 parity | Move stays active | temporary snapping and hover preview clear | pivot restored, Edit Pivot stays on | TODO |
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

## Manipulator persistence and snap source

The manipulator is never rebuilt or hidden by a drag or by a snap key: it stays on screen, follows
the transform and only changes what is drawn inside it. The snap source is the pivot the user sees,
so that pivot lands exactly on the target.

Automated coverage (`editor_transform` suite): `transform_snap_test.cc` pins the snap-source and
excluded-pivot decisions, `transform_gizmo_3d_test.cc` pins which handles a drag keeps on screen and
the centre glyph of each preset. What stays manual is only whether the result looks right on screen
— the headless runner has no persistent View3D gizmo group to render.

| Start mode | Tool before | Keys | Mouse | Expected manipulator | Expected snap result | Cancel |
| --- | --- | --- | --- | --- | --- | --- |
| Object, one object | Move | none | drag the centre square | whole manipulator stays visible and follows the object; the centre square becomes a circle | n/a | manipulator restored, centre square back |
| Object, one object | Move | none | drag an axis handle | whole manipulator stays visible; the centre square becomes a circle for the duration of the drag | n/a | as above |
| Object, one object | Move | `V` hold | drag the centre square | manipulator never disappears; only the centre glyph changes | the visible pivot lands on the target vertex, not the centre of the selection | transform and glyph restored |
| Object, custom pivot offset from the origin | Move | `V` hold | drag | unchanged | pivot lands on the target; the offset between pivot and geometry is preserved | as above |
| Object, one object | Move | `V` hold | pointer still over the manipulator | unchanged | no snap onto the selection's own pivot — no dead zone around the manipulator | n/a |
| Object, Edit Pivot on | Move | `D` | none | rotation rings and a light blue view aligned circle appear *around* the Move handles; arrows keep their stems, length and position, plane handles stay; the centre square gains a circle and a diamond inside it for as long as the mode is on | n/a | n/a |
| Object, Edit Pivot on | Move | `D`, then `V` hold | LMB drag | manipulator is not rebuilt; the square and circle stay exactly as they were, the circle is indication only | pivot snapped to the target vertex | pivot restored |
| Object, Edit Pivot on | Move | `D` / `Insert` / `W`, `E`, `R` | none | switching the mode or the tool must not make the manipulator flicker: the layout and the centre glyph change in the same redraw | n/a | n/a |

## Active-axis MMB drag

Plain `MMB` starts the active transform tool constrained to the axis handle used most recently
(X before any handle has been used). The constraint follows the displayed Maya/custom orientation.
Releasing `MMB` confirms; `Esc` or `RMB` cancels the transform and its single undo step. `Alt+MMB`
remains viewport navigation and must never enter this path. Edit Pivot supports Move and Rotate;
Scale is consumed without starting a transform so it cannot accidentally affect the object.

| Start mode | Tool before | Last active axis | Mouse | Expected transform | Tool after | Cancel | Undo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Object, one object | Move | X | plain `MMB` drag | translation constrained to the displayed X axis | Move stays active | transform restored, Move stays active | transform restored |
| Object, one object | Rotate | Y | plain `MMB` drag | rotation constrained to the displayed Y axis | Rotate stays active | transform restored, Rotate stays active | transform restored |
| Object, one object | Scale | Z | plain `MMB` drag | Maya scale behavior constrained to the displayed Z axis | Scale stays active | transform restored, Scale stays active | transform restored |
| Object, Edit Pivot on | Move | X / Y / Z | plain `MMB` drag | pivot translation constrained to the displayed active axis; object unchanged | Move and Edit Pivot stay active | pivot restored, Edit Pivot stays active | pivot restored |
| Object, Edit Pivot on | Rotate | X / Y / Z | plain `MMB` drag | pivot rotation constrained to the displayed active axis; object unchanged | Rotate and Edit Pivot stay active | pivot restored, Edit Pivot stays active | pivot restored |
| Object, Edit Pivot on | Scale | any | plain `MMB` drag | no transform starts; pivot and object remain unchanged | Scale and Edit Pivot stay active | n/a | no undo step |
| Object, one object | Move / Rotate / Scale | any | `Alt+MMB` drag | viewport pans; no transform starts | tool unchanged | view restored | no undo step |
| Object, one object | Select | any | plain `MMB` drag | no transform starts and selection is unchanged | Select stays active | n/a | no undo step |

## Edit Pivot snap-target preview overlay

The preview is feedback only: it does not author the pivot or change selection. It uses
`rgba(0.15, 1.0, 0.35, 1.0)`, distinct from selection colors, and is visible only while Edit Pivot
has a valid hovered preview, a temporary snap key is held, and no transform is active.

| Start mode | Keys / state | Pointer target | Expected overlay | Pivot / selection | Clear condition |
| --- | --- | --- | --- | --- | --- |
| Object or Edit Mesh, Edit Pivot on | `X` / `C` / `V` held, no transform | vertex | bright green point on the target vertex | unchanged / unchanged | snap-key release, Edit Pivot exit, transform begin, or miss |
| Object or Edit Mesh, Edit Pivot on | `X` / `C` / `V` held, no transform | edge | bright green point at the snap position plus a line over the complete target edge | unchanged / unchanged | as above |
| Object or Edit Mesh, Edit Pivot on | `X` / `C` / `V` held, no transform | face | bright green point at the snap position plus a closed outline around the target polygon | unchanged / unchanged | as above |
| Object or Edit Mesh, Edit Pivot on | temporary snap key held | no valid target | no preview geometry | unchanged / unchanged | remains hidden until a valid target is hovered |

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
| Object | Select | `Shift` | LMB on object | adds that object without changing the existing selection | unchanged | Select | unchanged | n/a | previous selection restored |
| Object | Select | `Ctrl` | LMB on object | TODO — remove or toggle | unchanged | Select | unchanged | n/a | TODO |
| Object | Select | none | LMB drag marquee | replaces selection | unchanged | Select | unchanged | marquee cancelled, selection unchanged | previous selection restored |
| Object | Move / Rotate / Scale | none | LMB drag from empty space | draws the marquee — the tool key-map must not inherit the drag and start a transform | unchanged | unchanged | unchanged | marquee cancelled | previous selection restored |
| Object | Select | `Ctrl` / `Shift` / `Ctrl` `Shift` | LMB drag marquee | removes / toggles / adds, from the modifiers of the **press** that started the drag | unchanged | Select | unchanged | selection unchanged | previous selection restored |
| Object | Select | `Shift` | LMB drag marquee | TODO | unchanged | Select | unchanged | TODO | TODO |
| Object | Select | `Ctrl` | LMB drag marquee | TODO | unchanged | Select | unchanged | TODO | TODO |
| Object | Select | none | LMB on already selected object | selection unchanged | unchanged | Select | unchanged | n/a | no undo step |
| Object | Select | none | LMB through geometry (occluded object) | TODO — front-most only or through | unchanged | Select | unchanged | n/a | TODO |
| Edit Mesh | Select | none | LMB on component | replaces component selection | unchanged | Select | unchanged | n/a | previous selection restored |
| Edit Mesh | Select | `Shift` | LMB on component | adds that one component without changing the existing selection | unchanged | Select | unchanged | n/a | previous selection restored |
| Edit Mesh, face mode | Select | none / `Shift` / `Ctrl` / `Ctrl` `Shift` | LMB drag marquee overlapping a face | replaces / toggles / removes / adds every face whose projected area overlaps the marquee; all four operations use the same hit rule | unchanged | Select | unchanged | selection unchanged | previous selection restored |
| Edit Mesh, shaded, X-Ray off | Select | any selection modifiers | LMB drag marquee across visible and occluded components | applies the marquee operation only to components with a clear line of sight from the view | unchanged | Select | unchanged | selection unchanged | previous selection restored |
| Edit Mesh, Wireframe or X-Ray on | Select | any selection modifiers | LMB drag marquee across visible and occluded components | applies the marquee operation to every component hit in projection, including components behind the visible surface | unchanged | Select | unchanged | selection unchanged | previous selection restored |
| Edit Mesh | Select | `Ctrl` `Shift` | LMB click without dragging | unchanged — the chord is reserved for the additive marquee | unchanged | Select | unchanged | n/a | no undo step |
| Edit Mesh | Select | `Ctrl` `Shift` | LMB drag marquee | adds every component hit by the marquee; it never falls back to a single-component pick | unchanged | Select | unchanged | selection unchanged | previous selection restored |
| Edit Mesh, face mode | Select | `Ctrl` `Shift` | LMB drag marquee wholly inside an unselected face | adds every face whose projected area overlaps the marquee; the center and vertices need not be inside | unchanged | Select | unchanged | selection unchanged | previous selection restored |
| Edit Mesh, face mode | Select | `Ctrl` | LMB drag marquee wholly inside a selected face | removes every selected face whose projected area overlaps the marquee; the center and vertices need not be inside | unchanged | Select | unchanged | selection unchanged | previous selection restored |
| Object, Edit Pivot | Edit Pivot | none | LMB in the viewport | **unchanged** — the pivot click operator consumes the event | pivot moves to the clicked point | Edit Pivot | unchanged | pivot restored | pivot restored |

The last row is the double-event guard: a pivot click must never also change the
selection.

While the pointer is over the 3D View, pure `Ctrl` shows a red minus cursor preview and
`Ctrl` + `Shift` shows a green plus cursor preview. The preview is hidden during navigation,
transforms and Edit Pivot.

## Topological selection

| Start mode | Tool before | Keys | Mouse | Selection | Pivot | Tool after | Snapping | Cancel | Undo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Edit Mesh, edge mode | Select | none | LMB double click on an edge | replaces selection with the edge loop; the loop stops at poles, triangles, n-gons and open boundaries | unchanged | Select | unchanged | n/a | previous selection restored |
| Edit Mesh, face mode | Select | none | LMB double click on a face | replaces selection with every face in the connected shell; seams and other edge marks do not split the shell | unchanged | Select | unchanged | n/a | previous selection restored |
| Edit Mesh, vertex mode | Select | none | LMB double click on a vertex | replaces selection with the vertex loop | unchanged | Select | unchanged | n/a | previous selection restored |
| Edit Mesh, edge mode, one edge selected | Select | `Shift` or `Ctrl Shift` | LMB double click on a second edge | **adds** the complete edge loop of the second edge, whatever is already selected | unchanged | Select | unchanged | n/a | previous selection restored |
| Edit Mesh, edge mode, one edge selected | Select | `Shift` | LMB double click on the opposite edge of a quad | **adds** the edge ring | unchanged | Select | unchanged | n/a | previous selection restored |
| Edit Mesh, face mode, one face selected | Select | `Shift` | LMB double click on a neighboring face | **adds** the complete face loop through their shared edge | unchanged | Select | unchanged | n/a | previous selection restored |
| Edit Mesh, face mode, one face selected | Select | `Shift` | LMB double click on a non-neighboring face | **adds** the shortest face path between the two | unchanged | Select | unchanged | n/a | previous selection restored |
| Edit Mesh, vertex mode, one vertex selected | Select | `Shift` | LMB double click on a second vertex | **adds** the vertex loop or path between the two | unchanged | Select | unchanged | n/a | previous selection restored |
| Edit Mesh, any component mode | Select | `Shift` `.` | none | grows the selection by one topological level; repeats | unchanged | Select | unchanged | n/a | one level restored per undo step |
| Edit Mesh, any component mode | Select | `Shift` `,` | none | shrinks the selection by one outer layer; repeats | unchanged | Select | unchanged | n/a | one level restored per undo step |
| Object | Select | `Shift` `.` / `Shift` `,` | none | **unchanged** — topological growth has no meaning between objects | unchanged | Select | unchanged | n/a | no undo step |
| Edit Mesh, edge mode | Select | none | LMB double click, then release the button | selection **stays** the loop — the release must not also count as a click | unchanged | Select | unchanged | n/a | previous selection restored |

The last row is the double-event guard of this section: a handled button event
must not be followed by a synthesized click. Blender clears that pending click
when a key-map handles the button; the Maya dispatcher runs before the key-maps,
so `wm_event_do_handlers` clears it there too.

These gestures are dispatched by the Maya interaction model before any keymap
runs, so the keymap must not carry a second binding for them. `Maya.py` drops the
base `mesh.loop_select` and `mesh.edgering_select` double-click items for exactly
that reason, and `Shift` `.` / `Shift` `,` are left unbound by the base keymap.
`Alt` stays reserved for navigation: `Alt` double click selects nothing.

In Edit Mesh, `Ctrl+E` invokes only Blender's standard context Extrude-and-Move operator. The
event is consumed even when Extrude cannot run, so neither the Edge menu nor an Extrude tool switch
may follow it.

## Multi-Cut

| Start mode | Tool before | Keys | Mouse | Geometry / preview | Tool after | Undo / redo |
| --- | --- | --- | --- | --- | --- | --- |
| Edit Mesh, no point placed | Multi-Cut | `Ctrl` | LMB over an edge ring | previews and inserts an edge loop | Multi-Cut | `Z` removes it; `Shift+Z` restores it |
| Edit Mesh, no point placed, a large edge-loop preview is visible | Multi-Cut | `Ctrl` or `Ctrl Shift` | hover the edge ring | draws only the current loop preview markers; stale hover and cut-start markers are not drawn elsewhere in the viewport | Multi-Cut remains active | unchanged |
| Edit Mesh, no point placed, a visually four-sided ring face has extra boundary vertices from a detailed cap | Multi-Cut | `Ctrl` or `Ctrl Shift` | LMB over the edge ring | treats the face as a logical quad, chooses its geometrically opposite edge, and inserts every previewed segment; a true triangle still stops the ring | Multi-Cut remains active | `Z` removes the loop in place; `Shift+Z` restores it without leaving Multi-Cut |
| Edit Mesh, no point placed | Multi-Cut | none | MMB drag across the mesh | performs a Quick Slice immediately on release; the geometry is materialized and no slice control points remain | Multi-Cut remains active | `Z` removes the complete slice in place; redo restores it |
| Edit Mesh, no point placed | Multi-Cut | none | finish a slice gesture whose expanded line misses the mesh | creates no cut and leaves no yellow/white control points or empty undo action | Multi-Cut remains active | unchanged |
| Edit Mesh, no point placed | Multi-Cut | none or `Shift` | LMB slice drag, then release | keeps the editable slice result but hides its yellow/white drag handles as soon as the gesture ends; handles are drawn again only while an endpoint or the slice plane is actively moved | Multi-Cut remains active | `Z` removes the slice; redo restores it |
| Edit Mesh, cut segment placed | Multi-Cut | `Ctrl Shift` | hover and click near the previous point | grey 90/180 degree guides appear and the active constrained cut is green | Multi-Cut | `Z` removes the point; `Shift+Z` restores it |
| Edit Mesh, cut segment placed | Multi-Cut | `Ctrl Shift` | hover an existing edge | previews the perpendicular foot on that edge, highlights the target edge, and shows a green right-angle marker | Multi-Cut | clicking creates one point action; `Z`/`Shift+Z` undo/redo it |
| Edit Mesh, several cut points placed | Multi-Cut | navigate the view, then edit a point | drag the last or an earlier point | only the edited endpoint and its connected segments change; every untouched cut vertex remains at its saved surface position | Multi-Cut | undo/redo restores the same surface positions in the new view |
| Edit Mesh, an incomplete segment lies wholly inside one face | Multi-Cut | none | `RMB` or `Enter` | completes any valid face split; a dangling segment that cannot split the face is discarded together with its temporary vertices | Multi-Cut remains active | no isolated vertices are left in the mesh |
| Edit Mesh | Multi-Cut | `1` / `2` / `3` | none | switches between control mesh, subdivision preview with cage, and subdivision surface preview; placed cuts are committed before the evaluated cage is rebuilt | Multi-Cut remains active | the committed cut and preview-mode change remain separate undo steps |
| Edit Mesh | Multi-Cut | `Ctrl+2` / `Ctrl+3` | none | toggles Object X-Ray / Viewport X-Ray through the standard Maya viewport commands | Multi-Cut remains active | unchanged |

The selection modifier plus/minus cursor is hidden while Multi-Cut owns the viewport. Its `Ctrl`
and `Ctrl Shift` gestures belong to edge-loop and perpendicular-cut previews, not selection.
The modal map also accepts the workspace aliases `Ctrl+Z` and `Ctrl+Shift+Z`, because global
undo/redo shortcuts cannot receive those events while Multi-Cut owns the modal event loop.
The workspace status line lists only Multi-Cut gestures and changes with the current state: loop and
slice-start shortcuts before a point, point-edit constraints during a cut, and slice movement after
a slice. Global viewport display commands remain available but are not presented as tool shortcuts.

## Marking menus

Every Maya marking menu is visible on the press that invokes it; it has no hidden popup-delay
phase. Plain `RMB`, `Ctrl+RMB`, and `Ctrl+Shift+RMB` remain distinct component, selection-conversion,
and active-transform-tool menus. Holding `Q`, `W`, `E`, or `R` while pressing `LMB` opens the
Select, Move, Rotate, or Scale menu respectively, independently of which tool was active before the
gesture. Move, Rotate, and Scale each write World, Object, and Component orientation to their own
Blender transform-orientation slot; Rotate additionally exposes Gimbal. The shared constraint,
Shift Extrude, Shift Duplicate,
Preserve UVs, Preserve Children, and Tweak Mode rows keep one live state across the menus. The
Select menu exposes Selection Constraints, Camera Based Selection, Highlight Backfaces, and the
two Shift-drag toggles. In particular, `W+LMB` opens the Move orientation menu while Edit Pivot is
active, including when `D` is still physically held and occupies Blender's generic key-modifier.
Multi-Cut's `Ctrl+Shift+RMB` menu uses the same native Maya marking-menu registration, radius, dead
zone, immediate visibility, directional selection, and release-to-confirm behavior as those tool
menus; it is not a separate Python `call_menu_pie` implementation.

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
