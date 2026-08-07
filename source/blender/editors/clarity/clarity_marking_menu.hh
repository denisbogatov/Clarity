/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 *
 * State behind the Clarity tool marking menus.
 *
 * The menu draws nothing of its own: every item asks the owner of that setting what it is right
 * now. Clarity's own menus work the same way, and it is the only arrangement that cannot drift, which
 * matters here because most of these settings can also be changed from somewhere else.
 *
 * Deliberately its own header instead of a section of `clarity_runtime.hh`: only the menus, runtime
 * and operators that write these settings need the types.
 */

#pragma once

#include <cstdint>

#include "ED_clarity.hh"

namespace blender {

struct bContext;

namespace ed::clarity {

enum class ClarityToolID : uint8_t;

/**
 * Which space a transform-tool manipulator is oriented in. One state, not independent checkboxes:
 * the modes exclude each other, as they do in Clarity's Move, Rotate and Scale contexts.
 */
enum class ClarityMoveOrientation : uint8_t {
  /** Clarity `mode = 0`: the local axes of each object. */
  Object = 0,
  /** Clarity `mode = 2`: the global axes of the scene. Clarity's default. */
  World = 1,
  /** Clarity `mode = 10`: the averaged frame of the selected components, driven by their normals. */
  Component = 2,
  /** Rotate Tool only: derive axes from the object's Euler rotation order. */
  Gimbal = 3,
  /**
   * Clarity `mode = 6`, its Custom axis orientation: the frame the pivot was authored with. No menu
   * offers it, which is the point - in Clarity the marking menu shows nothing checked while custom
   * pivot editing is on, because the mode it switched to is not one of the entries. Reported, never
   * requested: #transform_orientation_set is only ever asked for a mode the menu can show.
   */
  Custom = 4,
};

/**
 * Clarity's `polySelectConstraint`. Not part of the Move Tool at all, which is why it is owned by the
 * selection settings and not by #ClarityMoveToolSettings: it changes how a click or a marquee grows a
 * component selection, it stays active until it is turned off, and both marking menus that show it
 * have to be looking at the same state.
 */
enum class ClaritySelectionConstraint : uint8_t {
  Off = 0,
  Angle = 1,
  Border = 2,
  EdgeLoop = 3,
  EdgeRing = 4,
  Shell = 5,
};

/* #ClarityTransformConstraint lives in `ED_clarity.hh`: the transform module has to read it to honor it,
 * and this header is private to the Clarity editor. */

/** The independent toggles of the Move Tool marking menu, named so one operator can serve them. */
enum class ClarityMoveOption : uint8_t {
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
struct ClarityMoveToolSettings {
  /** Clarity `snapComponentsRelative`. */
  bool keep_spacing = true;
  /** Clarity `tweakMode`. */
  bool tweak_mode = false;
  /** Clarity `interactiveUpdate`, which only means anything while the manipulator follows normals. */
  bool update_triad = true;
  ClarityTransformConstraint transform_constraint = ClarityTransformConstraint::Off;
};

/** Snapshot of the shared transform-menu state, gathered from the real owners. */
struct ClarityMoveToolState {
  ClarityMoveOrientation orientation = ClarityMoveOrientation::World;
  bool keep_spacing = true;
  bool shift_extrude = true;
  bool shift_duplicate = true;
  bool preserve_uvs = false;
  bool preserve_children = false;
  bool tweak_mode = false;
  bool update_triad = true;
  ClaritySelectionConstraint selection_constraint = ClaritySelectionConstraint::Off;
  ClarityTransformConstraint transform_constraint = ClarityTransformConstraint::Off;
};

/** Read the live state. Falls back to the defaults when there is no Clarity runtime yet. */
ClarityMoveToolState move_tool_state_get(const bContext *C);

/** Resolve the transform orientation owned by one Clarity transform tool. */
ClarityMoveOrientation transform_orientation_get(const bContext *C, ClarityToolID tool);
/**
 * `Custom axis orientation` of a transform tool: the frame Edit Pivot authors, which stays selected
 * after the mode ends until the user picks a coordinate system or the frame itself goes away.
 */
bool orientation_custom_get(const bContext *C, ClarityToolID tool);
void orientation_custom_set(const bContext *C, ClarityToolID tool, bool value);
/**
 * Give each transform tool its own coordinate system, seeded with the one it starts in: `Object` for
 * Rotate, `World` for Move and Scale. Runs until the user picks one for a tool, after which that
 * slot is left alone.
 */
void transform_orientation_defaults_ensure(bContext *C);


bool move_option_get(const ClarityMoveToolState &state, ClarityMoveOption option);
bool move_option_set(bContext *C, ClarityMoveOption option, bool value);

bool move_orientation_set(bContext *C, ClarityMoveOrientation orientation);
bool transform_orientation_set(bContext *C,
                               ClarityToolID tool,
                               ClarityMoveOrientation orientation);
bool selection_constraint_set(bContext *C, ClaritySelectionConstraint constraint);
bool transform_constraint_set(bContext *C, ClarityTransformConstraint constraint);

/** Registered marking menu for a Clarity tool, or null for tools without one. */
const char *tool_marking_menu_idname(ClarityToolID tool);

void register_marking_menu_types();

}  // namespace ed::clarity
}  // namespace blender
