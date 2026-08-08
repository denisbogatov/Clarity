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
