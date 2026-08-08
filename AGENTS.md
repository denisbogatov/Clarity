# Blender source workflow

This is the source tree of the Clarity fork. On the Windows workstation it sits inside a workspace
directory whose `../AGENTS.md` carries the full set of rules and applies in addition to this file.
In a plain clone of this repository - a macOS checkout, for example - that file is absent and this
one stands alone.

## Build commands

Native compilation is user-owned. Agents do not run builds or narrow compile checks: finish the
edits, then name the one command for the user to run.

- Windows: `go.bat`, in the workspace directory above this one.
- macOS: `clarity/mac/go.sh`, after `clarity/mac/setup.sh` has prepared the machine once.

Both entry points take the same flags and mean the same thing by them:

- no flag - build what changed, verify, launch, run the editor and Clarity suites;
- `--no-tests` - the user is iterating visually and a test relink would only cost time;
- `--no-launch` - the result is a test outcome, not something to look at;
- `--tests-only` - run the suites against the tree as it stands;
- `--python` - a Python-only edit: sync scripts and launch, no native build;
- `--trace` - a foreground session that also collects the manipulator and pivot traces;
- `--check` - report whether anything is stale without building;
- `--full` - reconfigure and rebuild from scratch.

One machine, one build tree, one script that owns it end to end. Build options live in the
configure step inside that script and nowhere else; the tree stores a hash of the script and
reconfigures itself when it changes, so editing that section is enough. Never propose a second
build tree, a second launcher, or a "quick" build with features switched off - `WITH_*` options
become preprocessor defines, and a define can change which fields a struct has. Do not suggest
deleting the build directory, `.ninja_deps` or `.ninja_log` to fix a build; `--full` is the
supported way to replace a tree.

Do not run or recommend `build.bat`, `build-debug.bat`, `make.bat`, `make`, `ALL_BUILD`, clean,
rebuild, installation or packaging for routine changes.

## Platform differences worth suspecting

The interaction layer rests on different foundations per platform: GHOST Cocoa against Win32,
Metal against OpenGL and Vulkan, Cmd against Ctrl in the keymaps. When manipulator, modifier or
pivot behaviour differs between the two machines, or when a `ui_opengl_test_clarity_pivot.*` case
fails on only one of them, suspect the platform before suspecting the change. The C++ suites
(`editor_*`) do not depend on it; the UI simulation tests start a real window and need a live
graphical session.

macOS builds for Apple Silicon only: Blender 5.2 LTS ships no precompiled macOS x86_64 libraries.

## Source edits

- Keep ordinary implementation work in the smallest relevant `.cc` files. In particular, do not
  introduce DNA/RNA, shared-header, generated-data, or build-system changes merely to hold runtime
  state or defaults that can be owned outside those systems.
- Never start a build while compiler processes from an earlier build are active. A timed-out command
  may have left those child processes running; wait for their real completion before continuing.
- Preserve each file's own line endings. LF is the rule in this tree, with the committed exceptions
  `source/blender/editors/interface/interface_widgets.cc`,
  `source/blender/editors/space_view3d/view3d_intern.hh` and
  `source/blender/editors/transform/transform_gizmo.hh`, which must stay CRLF. An editor that
  rewrites endings turns a ten-line change into a whole-file diff.
