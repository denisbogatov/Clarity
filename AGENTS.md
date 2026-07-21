# Blender source workflow

All workspace-level instructions in `../AGENTS.md` apply to this source tree. This file only clarifies
paths when commands are launched from `blender/`.

- For a final native incremental build, run `..\dev.bat --build-only` once after all edits are ready.
- If changes are confined to `scripts/`, run `..\sync-python.bat` and do not compile native code.
- Keep ordinary implementation work in the smallest relevant `.cc` files. In particular, do not
  introduce DNA/RNA, shared-header, generated-data, or build-system changes merely to hold runtime
  state or defaults that can be owned outside those systems.
- Never start a build while compiler processes from an earlier build are active. A timed-out command
  may have left those child processes running; wait for their real completion before continuing.
