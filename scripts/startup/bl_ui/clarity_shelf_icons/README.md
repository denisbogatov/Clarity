# Clarity shelf icons

Custom button images for the Clarity shelf. Any shelf button can use any icon from
here - a Python tool, a plain Blender operator, a built-in action - so an icon lives
here rather than inside whichever tool happened to need one first.

## Adding one

Drop a PNG in this folder. It is picked up with no other change: `scripts/` is copied
into the build tree whole, so a new file ships with the next `go.bat` and needs no
CMake or build-system entry.

Assign it to a button through **Custom Icon** in the shelf's Add/Edit Shelf Icon
dialog. The shelf re-reads an icon file when it changes on disk, so replacing a PNG
updates the button without restarting Blender.

## Format

- PNG with alpha, square, 128×128. Blender scales it down for the button, and a
  transparent background is what lets it sit on the shelf without a visible plate.
- Legible at roughly 32 px. Whatever detail does not survive that size is only
  costing file size.

## Referring to one from a default shelf

`assets/clarity_shelf_default*.json` is tracked in git and read on every machine, so
it cannot contain an absolute path. It writes a placeholder instead, expanded by
`_clarity_shelf_resolve_bundled_path` in `space_topbar.py`:

```json
"custom_icon": "{shelf_icons}/tree_vertex_data_baker.png"
```

`{shelf_scripts}/` works the same way for the tool folders next door. A path the user
picked themselves is stored absolute and left untouched.
