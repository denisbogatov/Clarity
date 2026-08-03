/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 *
 * State behind the Maya tool marking menus.
 *
 * The menu draws nothing of its own: every item asks the owner of that setting what it is right
 * now. Maya's own menus work the same way, and it is the only arrangement that cannot drift, which
 * matters here because most of these settings can also be changed from somewhere else.
 *
 * Deliberately its own header instead of a section of `maya_runtime.hh`: only the menus, runtime
 * and operators that write these settings need the types.
 */

#pragma once

#include <cstdint>

#include "ED_maya.hh"

namespace blender {

struct bContext;

namespace ed::maya {

enum class MayaToolID : uint8_t;

/**
 * Which space a transform-tool manipulator is oriented in. One state, not independent checkboxes:
 * the modes exclude each other, as they do in Maya's Move, Rotate and Scale contexts.
 */
enum class MayaMoveOrientation : uint8_t {
  /** Maya `mode = 0`: the local axes of each object. */
  Object = 0,
  /** Maya `mode = 2`: the global axes of the scene. Maya's default. */
  World = 1,
  /** Maya `mode = 10`: the averaged frame of the selected components, driven by their normals. */
  Component = 2,
  /** Rotate Tool only: derive axes from the object's Euler rotation order. */
  Gimbal = 3,
};

/**
 * Maya's `polySelectConstraint`. Not part of the Move Tool at all, which is why it is owned by the
 * selection settings and not by #MayaMoveToolSettings: it changes how a click or a marquee grows a
 * component selection, it stays active until it is turned off, and both marking menus that show it
 * have to be looking at the same state.
 */
enum class MayaSelectionConstraint : uint8_t {
  Off = 0,
  Angle = 1,
  Border = 2,
  EdgeLoop = 3,
  EdgeRing = 4,
  Shell = 5,
};

/* #MayaTransformConstraint lives in `ED_maya.hh`: the transform module has to read it to honor it,
 * and this header is private to the Maya editor. */

/** The independent toggles of the Move Tool marking menu, named so one operator can serve them. */
enum class MayaMoveOption : uint8_t {
  KeepSpacing = 0,
  ShiftExtrude = 1,
  ShiftDuplicate = 2,
  PreserveUVs = 3,
  PreserveChildren = 4,
  TweakMode = 5,
  UpdateTriad = 6,
};

/**
 * The part of the Move Tool state this fork owns itself.
 *
 * The rest of the menu reads Blender's own settings instead, because those already exist and are
 * reachable from other places in the interface: a second copy here would be a second truth.
 */
struct MayaMoveToolSettings {
  /** Maya `snapComponentsRelative`. */
  bool keep_spacing = true;
  /** Maya `tweakMode`. */
  bool tweak_mode = false;
  /** Maya `interactiveUpdate`, which only means anything while the manipulator follows normals. */
  bool update_triad = true;
  MayaTransformConstraint transform_constraint = MayaTransformConstraint::Off;
};

/** Snapshot of the shared transform-menu state, gathered from the real owners. */
struct MayaMoveToolState {
  MayaMoveOrientation orientation = MayaMoveOrientation::World;
  bool keep_spacing = true;
  bool shift_extrude = true;
  bool shift_duplicate = true;
  bool preserve_uvs = false;
  bool preserve_children = false;
  bool tweak_mode = false;
  bool update_triad = true;
  MayaSelectionConstraint selection_constraint = MayaSelectionConstraint::Off;
  MayaTransformConstraint transform_constraint = MayaTransformConstraint::Off;
};

/** Read the live state. Falls back to the defaults when there is no Maya runtime yet. */
MayaMoveToolState move_tool_state_get(const bContext *C);

/** Resolve the transform orientation owned by one Maya transform tool. */
MayaMoveOrientation transform_orientation_get(const bContext *C, MayaToolID tool);

bool move_option_get(const MayaMoveToolState &state, MayaMoveOption option);
bool move_option_set(bContext *C, MayaMoveOption option, bool value);

bool move_orientation_set(bContext *C, MayaMoveOrientation orientation);
bool transform_orientation_set(bContext *C,
                               MayaToolID tool,
                               MayaMoveOrientation orientation);
bool selection_constraint_set(bContext *C, MayaSelectionConstraint constraint);
bool transform_constraint_set(bContext *C, MayaTransformConstraint constraint);

/** Registered marking menu for a Maya tool, or null for tools without one. */
const char *tool_marking_menu_idname(MayaToolID tool);

void register_marking_menu_types();

}  // namespace ed::maya
}  // namespace blender
