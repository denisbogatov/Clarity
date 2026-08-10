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

## Gestures no command performs

Dragging the pivot manipulator with `V`, `C` or `X` held, and picking a component with a modifier
click, exist only while a hand is on the mouse - which is why they are the last behaviors of this
fork with no reference numbers at all. `capture_reference_gestures.py` is the notebook for them: it
builds the same fixture scene, prints one instruction at a time, and snapshots after each, writing
the file on every call so a mistyped line costs one step rather than the session.

The run is automated. `capture_reference_autopilot.py` performs every gesture with nobody at the
mouse and writes the artifact in one call:

```python
import sys; sys.path.append(r"S:\Clarity\blender\tests\pivot_reference")
import capture_reference_autopilot as autopilot
autopilot.run()
```

It rebuilds the scene, frames it, and for each step moves the real cursor and presses the real
buttons through the operating system's input queue - Maya cannot tell it from a person, which is the
point, since these behaviors exist only on that code path. Keep hands off the mouse while it runs.

Three pictures per step: before the gesture, half way through the drag with the button still down,
and after. They are grabs of the viewport itself rather than `playblast` renders, because a render
draws the scene through the camera and leaves out the manipulator, the snap highlight and everything
else a gesture is actually about; the drag is drawn on top of the picture - green where the button
went down, red where it came up, and what was held. The mid-drag frame is the only one that shows
the manipulator being dragged, since the release takes it all away. If the grab fails - Maya
minimised, a screen that will not give up its pixels - a `playblast` is written instead, which is
worth having and worth knowing is not the same thing.

What it cannot promise is that a synthesized gesture *took*: a drag that missed the manipulator, a
hotkey the viewport did not have focus for, a snap that found nothing. So no step is trusted for
having been sent - each is judged by what actually moved and by what Maya echoed, and the ones that
did nothing say `ЖЕСТ НЕ СРАБОТАЛ` in the log and carry a `verdict` in the record. Those are the
ones to redo by hand.

The window is the front for all of it, and the place to start if you would rather press one button
than remember a call:

```python
import sys, importlib
sys.path.append(r"S:\Clarity\blender\tests\pivot_reference")
import capture_reference_window as window
importlib.reload(window)
window.show()
```

Its `Режим` menu has three: `Автопилот` runs the whole thing hands-off and hides the window while it
does, since the synthetic clicks land at desktop coordinates and a window over the viewport would
catch them; `Вручную: чек-лист пивота` walks the same steps with the buttons; `Вручную: свободная
запись` starts a session with no checklist at all, which is the mode a question about some other
tool starts in. The buttons of a mode that is not running are not pressable.

The two halves meet at `Доснять неудавшиеся вручную`: after an automated run the steps it reported
as `ЖЕСТ НЕ СРАБОТАЛ` become a hand-driven checklist of exactly those steps, written to a file of
its own so the automated artifact stays as it was recorded.

### Snap mode activation

The same window has a separate `Записать активацию снаппинга (X / C / V / J / Shift-J)` button.
It does not start a gesture session or replace the scene. It records the state machine that runs
*before* a snapped drag: each temporary key on its own (including repeats and stray releases), every
pair of overlapping keys in both release orders, all keys held together, and each temporary mode
over every persistent Status Line mode. Because J and Shift-J change a transform context rather
than a global `snapMode` flag, Move, Rotate and Scale are captured separately.

The entered output path gets `_snap_activation` appended. Three files are written:

- `.json` contains every state and the exact difference after each transition;
- `.log` is the readable transition-by-transition summary;
- `_history.mel` is Maya's complete command echo.

Every snapshot queries all flags of Maya's `snapMode` command, the discrete snap settings of all
three transform contexts, the current context, and the pivot snap flags. Hotkey command names are
read from Maya's active hotkey table, so a customized binding is visible in the artifact. The
capture restores global snap modes, per-tool discrete snap settings, and the active tool even if a
scenario raises an error.

The same capture can be run without the window from Maya's Script Editor:

```python
import capture_reference_snapping as snapping
snapping.run(
    r"S:\Clarity\blender\tests\pivot_reference\fixtures\maya_2025_snap_activation"
)
```

### Snapping real models

`Записать снаппинг на моделях (заменит текущую сцену)` is the geometry half of the capture. Save
the open Maya scene first: the run creates `snapSubject`, a point-target cube, a mesh-center cube
and a NURBS curve, frames them in the active viewport, and moves the subject through native mouse
events. It covers point, curve, grid, mesh center, view plane, absolute/relative move steps, rotate
steps and scale steps.

The object-to-object section moves the `snapSubject` pivot onto a vertex and onto the ray center of
a second mesh. A separate vertex-to-vertex case first snaps the subject pivot to its own vertex,
then uses that geometry anchor to align it with a vertex of the target object. The capture also
repeats both targets while editing only the pivot: it must reach the other object while the subject
translation and world bounds remain unchanged. Finally, Shift-drag cases duplicate the subject
with point and mesh-center snapping, including a custom-pivot vertex-to-vertex copy. Those pass only
when the original stays in place, exactly one new transform appears, and the duplicate reaches the
target.

The extended suite contains 55 isolated interactions. Besides the core cases above it covers all
X/Y/Z and XY/XZ/YZ move handles, Object space, transformed and negative-scale parents, target
pivots, pivot orientation, rotate/scale/reset after a custom pivot, Copy versus Instance smart
duplicates, reversed modifier order, modifier-first release, sequential duplicates, curved and
closed NURBS curves, curve CVs, custom grid spacing, a live surface, an asymmetric mesh center,
multiple objects, component spacing, orthographic view-plane movement, ambiguous targets, frozen
transforms, Escape cancellation, tool changes during a drag, and Undo/Redo. Every case starts from
a restored transform, pivot, topology, camera, grid and selection state so a component-baked scale
or a changed tool preference cannot leak into the next result.

The curve case uses Maya's conventional middle-mouse drag with C. Discrete move uses the X-axis
handle, so absolute and relative stepping are measured independently from a deliberately
non-integral starting position. Scale is judged from the model's world bounding box as well as its
transform channels, because Maya may bake a world-space axis scale into mesh components.

Each test records the subject transform before and after, all target geometry, the numeric distance
to the target, Maya's commands, and before/drag/after viewport screenshots. View-plane movement is
also checked against the active camera direction. Outputs use the
`_model_snapping` suffix. `PASS` means the model actually moved and landed on the measured target;
merely enabling a flag cannot pass a model test.

On macOS Maya needs permission under **System Settings → Privacy & Security → Accessibility**. Add
Maya, restart it, and then run the button. The capture checks this before replacing the scene. On
Windows it continues to use native `SendInput`.

Direct Script Editor entry point:

```python
import capture_reference_model_snapping as model_snapping
model_snapping.run(
    "/Users/denisbogatov/Documents/DCC/Clarity/tests/pivot_reference/fixtures/"
    "maya_2025_model_snapping"
)
```

### The same model scenarios in Clarity/Blender

`capture_clarity_model_snapping.py` uses the exact same ordered `(name, mode, tool)` contract and
schema 7 as the Maya model suite. The current parity boundary is all 54 implemented scenarios. It
recreates every scene for every case, writes before/after
state, changed fields, numeric assertions and viewport screenshots, and automatically writes a
Maya comparison beside the Blender result when the Maya fixture is present.

`live_surface_snap` stays in the canonical 55-name schema but is explicitly excluded from execution
until Live Surface exists in this fork.

On this Mac the current Clarity executable and repository paths are:

```bash
cd "/Users/denisbogatov/Documents/DCC/Clarity"
"/Users/denisbogatov/ClarityBuild52/bin/Blender.app/Contents/MacOS/Blender" \
  --factory-startup \
  --python tests/pivot_reference/capture_clarity_model_snapping.py -- \
  --output tests/pivot_reference/fixtures/clarity_model_snapping.json --count 55 --quit
```

Do not add `--background`: screenshots and the View3D context need a real window. To run it from
the UI instead, open `capture_clarity_model_snapping.py` in Blender's Text Editor and press **Run
Script**, then open **3D Viewport → Sidebar (`N`) → Clarity → Clarity Snap Tests** and press **Run
Run All 54 Supported Tests**. **Run First 20 Maya Tests** remains available for the shorter core
pass; Live Surface is skipped by both buttons. The buttons replace the current scene, so save work
first.

The button writes these four primary reports:

- `fixtures/clarity_model_snapping.json` and `.log` — Blender outcomes;
- `fixtures/clarity_model_snapping_vs_maya.json` and `.log` — aligned Maya/Blender rows.

The Blender capture currently labels every row `executionFidelity: operator_equivalent`. This is
deliberate: the 55 names, scenes and outcome assertions are one-to-one, while physical mouse/key
routing is not claimed by a scripted placement. Native Clarity events remain covered by
`tests/python/ui_simulate/test_clarity_pivot.py`; the comparison report warns about this distinction
instead of presenting operator equivalence as native-input parity.

The comparison can also be regenerated without either DCC application:

```bash
python3 tests/pivot_reference/compare_model_snapping.py \
  --maya tests/pivot_reference/fixtures/maya_2025_pivot_gestures_model_snapping.json \
  --blender tests/pivot_reference/fixtures/clarity_model_snapping.json \
  --output tests/pivot_reference/fixtures/clarity_model_snapping_vs_maya.json
```

The instruction is on screen as a numbered list of the actions the gesture is made of - a gesture is
a sequence, and a hand halfway through one has to see where it is - `Записать` / `Пропустить` /
`Переснять` / `Завершить` are buttons, the note field feeds the next record, and the log grows
underneath. Everything on screen is in the language of the hand doing the work; every identifier,
and the `.json` and `.log` the session writes, stay in the language of the rest of this directory. The window also records **the commands Maya ran while
the gesture was performed**: a `cmdScrollFieldReporter` with `echoAllCommands` on is drained into
every record, so a step carries both where the pivot ended up and which command put it there. What
the recording itself echoes is dropped, not attributed to the next step.

The commands are collected by `capture_reference_commands.py`: one global sink, and no UI of its
own. It is Maya's own `scriptEditorInfo -writeHistory` file rather than a `cmdScrollFieldReporter`,
because a reporter is a control, a control needs a window, and an automated run has no business
opening one; reading the file from the last offset gives exactly the commands of the last step.

Maya talks to itself constantly - one click on an object echoes forty lines of panel, layer, HUD and
tool-settings refreshes around the one command that did something - so those are filtered out of the
records, `// Warning` and `// Error` lines deliberately kept, and the number of dropped lines is
always reported next to the number of kept ones. The deny list is at the top of that module,
measured from a real session of this workspace; it is a deny list and not an allow list because a
session about an unfamiliar tool is exactly where an unexpected command must not be hidden.

Unticking *Чек-лист по пивоту* starts a session with no steps at all, where the `Свободный снимок`
row records whatever is labelled and pressed. That is the shape for a question about some other
tool, where the steps are not known in advance - the window is not pivot-specific.

The same session is driveable by hand, and typing and pressing buttons can be mixed:

```python
import capture_reference_gestures as gestures
gestures.start(r"S:\Clarity\blender\tests\pivot_reference\fixtures\maya_2025_pivot_gestures")

gestures.status()          # reprint what to do now - the Script Editor scrolls
gestures.done()            # snapshot, print what changed, move on; done("note") to annotate
gestures.again()           # that gesture came out wrong: drop it and redo the step
gestures.skip("why")       # recorded as skipped, not as done
gestures.snapshot("label") # record something outside the checklist
gestures.finish()          # closing summary and the two paths
```

Each snapshot carries the world position of every vertex and edge midpoint next to the pivot, and
the step reports which of them the pivot is nearest and how far - so "did the snap land exactly on
the vertex or keep the grab offset" is answered by a number in the log rather than by an impression
of the viewport. No step names a vertex to aim at: which one was hit is read back afterwards.

The step list at the bottom of that module is meant to be edited; an entry is a name, an instruction
and the question its numbers answer.

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

Those nine are registered in `_ui_tests`, so `go.bat --tests-only` runs them - the tree is configured
with `WITH_UI_TESTS=ON` and the `ctest` filter selects `ui_opengl_test_clarity_pivot.*` out of the
upstream set that option brings with it. They start a real window like the capture does.

To run one by hand, point `BLENDER_CLARITY_SNAP_TRACE_FILE` somewhere readable - the assertions read
the click's own report out of that file, and unset it defaults to a per-process file in the temp
directory. **One name per Blender**: `run_blender_setup.py` accepts several, but `easy_keys.run` only
registers a timer and returns, so a second name starts a second generator that interleaves its events
with the first one's and fails it. `run.py` starts a process per test for that reason.

```powershell
$env:BLENDER_CLARITY_SNAP_TRACE_FILE = "$env:TEMP\clarity-uitest-trace.log"
& '<build>/bin/blender.exe' --enable-event-simulate --factory-startup `
  --python tests\python\ui_simulate\run_blender_setup.py -- --tests test_clarity_pivot.<name>
```

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
