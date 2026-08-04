/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 *
 * Clarity Select, Move, Rotate and Scale marking menus, their submenus and shared state.
 */

#include "clarity_marking_menu.hh"

#include "MEM_guardedalloc.h"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_view3d_types.h"
#include "DNA_windowmanager_types.h"

#include "BLI_assert.h"
#include "BLI_string_utf8.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_scene.hh"
#include "BKE_screen.hh"

#include "ED_screen.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "UI_interface_c.hh"
#include "UI_interface_layout.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_toolsystem.hh"
#include "WM_types.hh"

#include "clarity_runtime.hh"

namespace blender {
namespace ed::clarity {

/* -------------------------------------------------------------------- */
/** \name State
 *
 * Every setting is read from whoever really owns it. Four of them are Blender's own and are
 * reachable from other parts of the interface, so the menu must not keep a copy: it would be a
 * second truth that silently disagrees the moment the user changes one of them elsewhere.
 * \{ */

static int transform_orientation_slot_flag_get(const ClarityToolID tool)
{
  switch (tool) {
    case ClarityToolID::Move:
      return SCE_ORIENT_TRANSLATE;
    case ClarityToolID::Rotate:
      return SCE_ORIENT_ROTATE;
    case ClarityToolID::Scale:
      return SCE_ORIENT_SCALE;
    case ClarityToolID::None:
    case ClarityToolID::Select:
    case ClarityToolID::MultiCut:
    case ClarityToolID::TargetWeld:
    case ClarityToolID::QuadDraw:
      break;
  }
  return -1;
}

static TransformOrientationSlot *transform_orientation_slot_get(const bContext *C,
                                                                 const ClarityToolID tool,
                                                                 const bool activate_tool_slot)
{
  Scene *scene = CTX_data_scene(C);
  if (scene == nullptr) {
    return nullptr;
  }
  const int slot_flag = transform_orientation_slot_flag_get(tool);
  if (slot_flag < 0) {
    return nullptr;
  }
  if (!activate_tool_slot) {
    return BKE_scene_orientation_slot_get(scene, slot_flag);
  }

  TransformOrientationSlot *slot = &scene->orientation_slots[slot_flag];
  if (slot_flag != SCE_ORIENT_DEFAULT) {
    slot->flag |= SELECT;
  }
  return slot;
}

static ClarityMoveOrientation move_orientation_from_blender(const int orientation_type)
{
  switch (orientation_type) {
    case V3D_ORIENT_LOCAL:
      return ClarityMoveOrientation::Object;
    case V3D_ORIENT_NORMAL:
      return ClarityMoveOrientation::Component;
    case V3D_ORIENT_GIMBAL:
      return ClarityMoveOrientation::Gimbal;
    default:
      return ClarityMoveOrientation::World;
  }
}

static int move_orientation_to_blender(const ClarityMoveOrientation orientation)
{
  switch (orientation) {
    case ClarityMoveOrientation::Object:
      return V3D_ORIENT_LOCAL;
    case ClarityMoveOrientation::Component:
      /* Clarity builds the frame from the normals of the selected components and falls back to the
       * object's own axes for a whole object, which is what Blender's Normal orientation does. */
      return V3D_ORIENT_NORMAL;
    case ClarityMoveOrientation::Gimbal:
      return V3D_ORIENT_GIMBAL;
    case ClarityMoveOrientation::World:
      break;
  }
  return V3D_ORIENT_GLOBAL;
}

ClarityMoveToolState move_tool_state_get(const bContext *C)
{
  ClarityMoveToolState state;

  state.orientation = transform_orientation_get(C, ClarityToolID::Move);

  if (const ToolSettings *ts = CTX_data_tool_settings(C)) {
    state.preserve_uvs = (ts->uvcalc_flag & UVCALC_TRANSFORM_CORRECT) != 0;
    state.preserve_children = (ts->transform_flag & SCE_XFORM_SKIP_CHILDREN) != 0;
  }

  if (const ClarityWindowRuntime *runtime = runtime_get(C)) {
    state.shift_extrude = runtime->selection_settings.shift_extrude;
    state.shift_duplicate = runtime->selection_settings.shift_duplicate;
    state.keep_spacing = runtime->move_tool_settings.keep_spacing;
    state.tweak_mode = runtime->move_tool_settings.tweak_mode;
    state.update_triad = runtime->move_tool_settings.update_triad;
    state.selection_constraint = runtime->selection_settings.selection_constraint;
    state.transform_constraint = runtime->move_tool_settings.transform_constraint;
  }

  return state;
}

ClarityMoveOrientation transform_orientation_get(const bContext *C, const ClarityToolID tool)
{
  if (const TransformOrientationSlot *slot = transform_orientation_slot_get(C, tool, false)) {
    return move_orientation_from_blender(BKE_scene_orientation_slot_get_index(slot));
  }
  return ClarityMoveOrientation::World;
}

bool move_option_get(const ClarityMoveToolState &state, const ClarityMoveOption option)
{
  switch (option) {
    case ClarityMoveOption::KeepSpacing:
      return state.keep_spacing;
    case ClarityMoveOption::ShiftExtrude:
      return state.shift_extrude;
    case ClarityMoveOption::ShiftDuplicate:
      return state.shift_duplicate;
    case ClarityMoveOption::PreserveUVs:
      return state.preserve_uvs;
    case ClarityMoveOption::PreserveChildren:
      return state.preserve_children;
    case ClarityMoveOption::TweakMode:
      return state.tweak_mode;
    case ClarityMoveOption::UpdateTriad:
      return state.update_triad;
  }
  return false;
}

static void move_menu_state_changed(bContext *C, const bool affects_transform)
{
  WM_event_add_notifier(C, NC_SCENE | ND_TOOLSETTINGS, nullptr);
  if (affects_transform) {
    WM_event_add_notifier(C, NC_SCENE | ND_TRANSFORM, nullptr);
  }
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_VIEW3D, nullptr);
}

bool move_option_set(bContext *C, const ClarityMoveOption option, const bool value)
{
  switch (option) {
    case ClarityMoveOption::PreserveUVs:
    case ClarityMoveOption::PreserveChildren: {
      ToolSettings *ts = CTX_data_tool_settings(C);
      if (ts == nullptr) {
        return false;
      }
      if (option == ClarityMoveOption::PreserveUVs) {
        SET_FLAG_FROM_TEST(ts->uvcalc_flag, value, UVCALC_TRANSFORM_CORRECT);
      }
      else {
        SET_FLAG_FROM_TEST(ts->transform_flag, value, SCE_XFORM_SKIP_CHILDREN);
      }
      move_menu_state_changed(C, false);
      return true;
    }
    default:
      break;
  }

  ClarityWindowRuntime *runtime = runtime_ensure(C);
  if (runtime == nullptr) {
    return false;
  }
  switch (option) {
    case ClarityMoveOption::KeepSpacing:
      runtime->move_tool_settings.keep_spacing = value;
      break;
    case ClarityMoveOption::ShiftExtrude:
      runtime->selection_settings.shift_extrude = value;
      break;
    case ClarityMoveOption::ShiftDuplicate:
      runtime->selection_settings.shift_duplicate = value;
      break;
    case ClarityMoveOption::TweakMode:
      runtime->move_tool_settings.tweak_mode = value;
      break;
    case ClarityMoveOption::UpdateTriad:
      runtime->move_tool_settings.update_triad = value;
      break;
    case ClarityMoveOption::PreserveUVs:
    case ClarityMoveOption::PreserveChildren:
      BLI_assert_unreachable();
      return false;
  }
  move_menu_state_changed(C, false);
  return true;
}

bool move_orientation_set(bContext *C, const ClarityMoveOrientation orientation)
{
  return transform_orientation_set(C, ClarityToolID::Move, orientation);
}

bool transform_orientation_set(bContext *C,
                               const ClarityToolID tool,
                               const ClarityMoveOrientation orientation)
{
  if (orientation == ClarityMoveOrientation::Gimbal && tool != ClarityToolID::Rotate) {
    return false;
  }
  TransformOrientationSlot *slot = transform_orientation_slot_get(C, tool, true);
  if (slot == nullptr) {
    return false;
  }
  BKE_scene_orientation_slot_set_index(slot, move_orientation_to_blender(orientation));
  move_menu_state_changed(C, true);
  return true;
}

const char *tool_marking_menu_idname(const ClarityToolID tool)
{
  switch (tool) {
    case ClarityToolID::Select:
      return "VIEW3D_MT_clarity_select_marking_menu";
    case ClarityToolID::Move:
      return "VIEW3D_MT_clarity_move_marking_menu";
    case ClarityToolID::Rotate:
      return "VIEW3D_MT_clarity_rotate_marking_menu";
    case ClarityToolID::Scale:
      return "VIEW3D_MT_clarity_scale_marking_menu";
    case ClarityToolID::MultiCut:
      return "VIEW3D_MT_clarity_multi_cut_marking_menu";
    case ClarityToolID::None:
    case ClarityToolID::TargetWeld:
    case ClarityToolID::QuadDraw:
      break;
  }
  return nullptr;
}

bool selection_constraint_set(bContext *C, const ClaritySelectionConstraint constraint)
{
  ClarityWindowRuntime *runtime = runtime_ensure(C);
  if (runtime == nullptr) {
    return false;
  }
  runtime->selection_settings.selection_constraint = constraint;
  move_menu_state_changed(C, false);
  return true;
}

bool transform_constraint_set(bContext *C, const ClarityTransformConstraint constraint)
{
  ClarityWindowRuntime *runtime = runtime_ensure(C);
  if (runtime == nullptr) {
    return false;
  }
  runtime->move_tool_settings.transform_constraint = constraint;
  move_menu_state_changed(C, false);
  return true;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operators
 * \{ */

static const EnumPropertyItem clarity_move_orientation_items[] = {
    {int(ClarityMoveOrientation::Object),
     "OBJECT",
     0,
     "Object",
     "Orient the manipulator along the local axes of each selected object"},
    {int(ClarityMoveOrientation::World),
     "WORLD",
     0,
     "World",
     "Orient the manipulator along the global axes of the scene"},
    {int(ClarityMoveOrientation::Component),
     "COMPONENT",
     0,
     "Component",
     "Orient the manipulator along the averaged frame of the selected components"},
    {int(ClarityMoveOrientation::Gimbal),
     "GIMBAL",
     0,
     "Gimbal",
     "Orient the Rotate Tool along the object's Euler rotation axes"},
    {0, nullptr, 0, nullptr, nullptr},
};

static const EnumPropertyItem clarity_transform_tool_items[] = {
    {int(ClarityToolID::Move), "MOVE", 0, "Move", "Set the Move Tool orientation"},
    {int(ClarityToolID::Rotate), "ROTATE", 0, "Rotate", "Set the Rotate Tool orientation"},
    {int(ClarityToolID::Scale), "SCALE", 0, "Scale", "Set the Scale Tool orientation"},
    {0, nullptr, 0, nullptr, nullptr},
};

static const EnumPropertyItem clarity_camera_based_selection_menu_items[] = {
    {int(ClarityCameraBasedSelection::Off),
     "OFF",
     0,
     "Off",
     "Select through the mesh without camera-depth filtering"},
    {int(ClarityCameraBasedSelection::On),
     "ON",
     0,
     "On",
     "Use camera-depth filtering when the viewport supports it"},
    {int(ClarityCameraBasedSelection::Auto),
     "AUTO",
     0,
     "Auto",
     "Use camera-depth filtering in shaded non-X-Ray views"},
    {0, nullptr, 0, nullptr, nullptr},
};

static const EnumPropertyItem clarity_move_option_items[] = {
    {int(ClarityMoveOption::KeepSpacing),
     "KEEP_SPACING",
     0,
     "Keep Spacing",
     "Move the whole selection to the snap target as one instead of snapping it element by "
     "element"},
    {int(ClarityMoveOption::ShiftExtrude),
     "SHIFT_EXTRUDE",
     0,
     "Shift Extrude",
     "Let a Shift drag of the manipulator extrude the selected components"},
    {int(ClarityMoveOption::ShiftDuplicate),
     "SHIFT_DUPLICATE",
     0,
     "Shift Duplicate",
     "Let a Shift drag of the manipulator duplicate the selected objects"},
    {int(ClarityMoveOption::PreserveUVs),
     "PRESERVE_UVS",
     0,
     "Preserve UVs",
     "Correct the UVs of moved geometry so the texture keeps its placement"},
    {int(ClarityMoveOption::PreserveChildren),
     "PRESERVE_CHILDREN",
     0,
     "Preserve Children",
     "Keep children in place when their parent is moved"},
    {int(ClarityMoveOption::TweakMode),
     "TWEAK_MODE",
     0,
     "Tweak Mode",
     "Hide the manipulator and select-and-drag the component under the pointer directly"},
    {int(ClarityMoveOption::UpdateTriad),
     "UPDATE_TRIAD",
     0,
     "Update Triad",
     "Recompute the component orientation of the manipulator while the drag is running"},
    {0, nullptr, 0, nullptr, nullptr},
};

static const EnumPropertyItem clarity_selection_constraint_items[] = {
    {int(ClaritySelectionConstraint::Off), "OFF", 0, "Off", "Select components without any constraint"},
    {int(ClaritySelectionConstraint::Angle),
     "ANGLE",
     0,
     "Angle",
     "Grow the selection over connected components that stay inside an angle tolerance"},
    {int(ClaritySelectionConstraint::Border),
     "BORDER",
     0,
     "Border",
     "Grow the selection along the open border of the mesh"},
    {int(ClaritySelectionConstraint::EdgeLoop),
     "EDGE_LOOP",
     0,
     "Edge Loop",
     "Select the edge loop the picked edge belongs to"},
    {int(ClaritySelectionConstraint::EdgeRing),
     "EDGE_RING",
     0,
     "Edge Ring",
     "Select the edge ring the picked edge belongs to"},
    {int(ClaritySelectionConstraint::Shell),
     "SHELL",
     0,
     "Shell",
     "Grow the selection over the whole connected island of the mesh"},
    {0, nullptr, 0, nullptr, nullptr},
};

static const EnumPropertyItem clarity_transform_constraint_items[] = {
    {int(ClarityTransformConstraint::Off), "OFF", 0, "Off", "Move components freely"},
    {int(ClarityTransformConstraint::Edge),
     "EDGE",
     0,
     "Edge Slide",
     "Keep moved components on the edges they started on"},
    {int(ClarityTransformConstraint::Surface),
     "SURFACE",
     0,
     "Surface Slide",
     "Keep moved components on the surface of the mesh"},
    {0, nullptr, 0, nullptr, nullptr},
};

static wmOperatorStatus clarity_transform_orientation_set_exec(bContext *C, wmOperator *op)
{
  const ClarityMoveOrientation orientation = ClarityMoveOrientation(
      RNA_enum_get(op->ptr, "orientation"));
  const ClarityToolID tool = ClarityToolID(RNA_enum_get(op->ptr, "tool"));
  return transform_orientation_set(C, tool, orientation) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static void CLARITY_OT_transform_orientation_set(wmOperatorType *ot)
{
  ot->name = "Clarity Transform Orientation";
  ot->description = "Set the coordinate system of a Clarity transform-tool manipulator";
  ot->idname = "CLARITY_OT_transform_orientation_set";
  ot->exec = clarity_transform_orientation_set_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_enum(ot->srna,
               "tool",
               clarity_transform_tool_items,
               int(ClarityToolID::Move),
               "Tool",
               "");
  RNA_def_enum(ot->srna,
               "orientation",
               clarity_move_orientation_items,
               int(ClarityMoveOrientation::World),
               "Orientation",
               "");
}

static wmOperatorStatus clarity_move_option_toggle_exec(bContext *C, wmOperator *op)
{
  const ClarityMoveOption option = ClarityMoveOption(RNA_enum_get(op->ptr, "option"));
  /* The menu never tells the operator what to write: the toggle flips whatever the setting is at
   * the moment it runs, so a shortcut and a menu item can never disagree about the new value. */
  const bool value = !move_option_get(move_tool_state_get(C), option);
  return move_option_set(C, option, value) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static void CLARITY_OT_move_option_toggle(wmOperatorType *ot)
{
  ot->name = "Clarity Move Option";
  ot->description = "Toggle one independent option of the Clarity Move Tool";
  ot->idname = "CLARITY_OT_move_option_toggle";
  ot->exec = clarity_move_option_toggle_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER;

  RNA_def_enum(ot->srna,
               "option",
               clarity_move_option_items,
               int(ClarityMoveOption::KeepSpacing),
               "Option",
               "");
}

static wmOperatorStatus clarity_selection_constraint_set_exec(bContext *C, wmOperator *op)
{
  const ClaritySelectionConstraint constraint = ClaritySelectionConstraint(
      RNA_enum_get(op->ptr, "constraint"));
  return selection_constraint_set(C, constraint) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static void CLARITY_OT_selection_constraint_set(wmOperatorType *ot)
{
  ot->name = "Clarity Selection Constraint";
  ot->description = "Set how a component selection is filtered and grown";
  ot->idname = "CLARITY_OT_selection_constraint_set";
  ot->exec = clarity_selection_constraint_set_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER;

  RNA_def_enum(ot->srna,
               "constraint",
               clarity_selection_constraint_items,
               int(ClaritySelectionConstraint::Off),
               "Constraint",
               "");
}

static wmOperatorStatus clarity_transform_constraint_set_exec(bContext *C, wmOperator *op)
{
  const ClarityTransformConstraint constraint = ClarityTransformConstraint(
      RNA_enum_get(op->ptr, "constraint"));
  return transform_constraint_set(C, constraint) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static void CLARITY_OT_transform_constraint_set(wmOperatorType *ot)
{
  ot->name = "Clarity Transform Constraint";
  ot->description = "Constrain moved components to the geometry of the active mesh";
  ot->idname = "CLARITY_OT_transform_constraint_set";
  ot->exec = clarity_transform_constraint_set_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER;

  RNA_def_enum(ot->srna,
               "constraint",
               clarity_transform_constraint_items,
               int(ClarityTransformConstraint::Off),
               "Constraint",
               "");
}

static wmOperatorStatus clarity_tool_options_exec(bContext *C, wmOperator * /*op*/)
{
  /* Clarity's tool Options rows open Tool Settings. The sidebar Tool tab is where this fork keeps
   * them, so the command only has to make sure it is the visible one. */
  ScrArea *area = CTX_wm_area(C);
  if (area == nullptr || area->spacetype != SPACE_VIEW3D) {
    return OPERATOR_CANCELLED;
  }
  ARegion *region = BKE_area_find_region_type(area, RGN_TYPE_UI);
  if (region == nullptr) {
    return OPERATOR_CANCELLED;
  }
  ui::panel_category_active_set(region, "Tool");
  if (region->flag & RGN_FLAG_HIDDEN) {
    ED_region_toggle_hidden(C, region);
  }
  ED_region_tag_redraw(region);
  return OPERATOR_FINISHED;
}

static void CLARITY_OT_tool_options(wmOperatorType *ot)
{
  ot->name = "Clarity Tool Options";
  ot->description = "Show the settings of the active Clarity tool";
  ot->idname = "CLARITY_OT_tool_options";
  ot->exec = clarity_tool_options_exec;
  ot->poll = ED_operator_view3d_active;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Menus
 * \{ */

static bool marking_menu_poll(const bContext *C, MenuType * /*mt*/)
{
  const ARegion *region = CTX_wm_region(C);
  return CTX_wm_view3d(C) != nullptr && region != nullptr &&
         region->regiontype == RGN_TYPE_WINDOW;
}

static int check_icon(const bool active)
{
  /* Clarity marks an active toggle or the live entry of an exclusive group with a check, and leaves
   * the blue highlight to mean "under the pointer" alone. */
  return active ? ICON_CHECKBOX_HLT : ICON_CHECKBOX_DEHLT;
}

static void orientation_item(ui::Layout &layout,
                             const ClarityMoveToolState &state,
                             const char *name,
                             const ClarityToolID tool,
                             const ClarityMoveOrientation orientation)
{
  PointerRNA op_ptr = layout.op("CLARITY_OT_transform_orientation_set",
                                name,
                                check_icon(state.orientation == orientation),
                                wm::OpCallContext::ExecDefault,
                                UI_ITEM_NONE);
  RNA_enum_set(&op_ptr, "tool", int(tool));
  RNA_enum_set(&op_ptr, "orientation", int(orientation));
}

static void option_item(ui::Layout &layout,
                        const ClarityMoveToolState &state,
                        const char *name,
                        const ClarityMoveOption option)
{
  PointerRNA op_ptr = layout.op("CLARITY_OT_move_option_toggle",
                                name,
                                check_icon(move_option_get(state, option)),
                                wm::OpCallContext::ExecDefault,
                                UI_ITEM_NONE);
  RNA_enum_set(&op_ptr, "option", int(option));
}

static ClarityMoveToolState transform_tool_state_get(const bContext *C, const ClarityToolID tool)
{
  ClarityMoveToolState state = move_tool_state_get(C);
  state.orientation = transform_orientation_get(C, tool);
  return state;
}

static void transform_orientation_pie_draw(ui::Layout &pie,
                                           const ClarityMoveToolState &state,
                                           const ClarityToolID tool,
                                           const bool show_keep_spacing,
                                           const bool show_gimbal)
{
  /* Blender fills radial slots in the order W, E, S, N, NW, NE, SW, SE. Keep the coordinate
   * systems in the same directions for every transform tool so the learned gesture transfers. */
  orientation_item(pie, state, "World", tool, ClarityMoveOrientation::World); /* W */
  if (show_gimbal) {
    orientation_item(pie, state, "Gimbal", tool, ClarityMoveOrientation::Gimbal); /* E */
  }
  else {
    pie.separator(); /* E */
  }
  pie.separator();                                                         /* S */
  pie.separator();                                                         /* N */
  orientation_item(pie, state, "Object", tool, ClarityMoveOrientation::Object);       /* NW */
  orientation_item(pie, state, "Component", tool, ClarityMoveOrientation::Component); /* NE */
  pie.separator();                                                                  /* SW */
  if (show_keep_spacing) {
    option_item(pie, state, "Keep Spacing", ClarityMoveOption::KeepSpacing); /* SE */
  }
  else {
    pie.separator(); /* SE */
  }
}

static void transform_common_list_draw(ui::Layout &list,
                                       const ClarityMoveToolState &state,
                                       const char *options_label,
                                       const bool show_update_triad)
{
  list.menu("VIEW3D_MT_clarity_selection_constraints", "Selection Constraints", ICON_BLANK1);
  list.menu("VIEW3D_MT_clarity_transform_constraints", "Transform Constraints", ICON_BLANK1);
  list.separator();
  option_item(list, state, "Shift Extrude", ClarityMoveOption::ShiftExtrude);
  option_item(list, state, "Shift Duplicate", ClarityMoveOption::ShiftDuplicate);
  option_item(list, state, "Preserve UVs", ClarityMoveOption::PreserveUVs);
  option_item(list, state, "Preserve Children", ClarityMoveOption::PreserveChildren);
  option_item(list, state, "Tweak Mode", ClarityMoveOption::TweakMode);
  if (show_update_triad) {
    option_item(list, state, "Update Triad", ClarityMoveOption::UpdateTriad);
  }
  list.separator();
  list.op("CLARITY_OT_tool_options",
          options_label,
          ICON_BLANK1,
          wm::OpCallContext::ExecDefault,
          UI_ITEM_NONE);
}

static ClaritySelectionSettings selection_settings_get(const bContext *C)
{
  if (const ClarityWindowRuntime *runtime = runtime_get(C)) {
    return runtime->selection_settings;
  }
  return {};
}

static void selection_boolean_item(ui::Layout &layout,
                                   const char *name,
                                   const char *property,
                                   const bool value)
{
  PointerRNA op_ptr = layout.op("CLARITY_OT_selection_settings_set",
                                name,
                                check_icon(value),
                                wm::OpCallContext::ExecDefault,
                                UI_ITEM_NONE);
  RNA_boolean_set(&op_ptr, property, !value);
}

static void clarity_select_marking_menu_draw(const bContext *C, Menu *menu)
{
  const ClaritySelectionSettings selection = selection_settings_get(C);
  const ClarityMoveToolState common = move_tool_state_get(C);

  ui::Layout &pie = menu->layout->menu_pie();
  pie.menu("VIEW3D_MT_clarity_selection_constraints", "Selection Constraints", ICON_NONE); /* W */
  pie.menu("VIEW3D_MT_clarity_camera_based_selection", "Camera Based Selection", ICON_NONE); /* E */
  pie.separator();                                                                      /* S */
  selection_boolean_item(
      pie, "Highlight Backfaces", "highlight_backfaces", selection.highlight_backfaces); /* N */
  pie.separator(); /* NW */
  pie.separator(); /* NE */
  pie.separator(); /* SW */
  pie.separator(); /* SE */

  ui::Layout &list = menu->layout->column(false);
  option_item(list, common, "Shift Extrude", ClarityMoveOption::ShiftExtrude);
  option_item(list, common, "Shift Duplicate", ClarityMoveOption::ShiftDuplicate);
  list.separator();
  list.op("CLARITY_OT_tool_options",
          "Select Options",
          ICON_BLANK1,
          wm::OpCallContext::ExecDefault,
          UI_ITEM_NONE);
}

static void clarity_move_marking_menu_draw(const bContext *C, Menu *menu)
{
  const ClarityMoveToolState state = transform_tool_state_get(C, ClarityToolID::Move);
  ui::Layout &pie = menu->layout->menu_pie();
  transform_orientation_pie_draw(pie, state, ClarityToolID::Move, true, false);

  ui::Layout &list = menu->layout->column(false);
  transform_common_list_draw(list, state, "Move Options", true);
}

static void clarity_rotate_marking_menu_draw(const bContext *C, Menu *menu)
{
  const ClarityMoveToolState state = transform_tool_state_get(C, ClarityToolID::Rotate);
  ui::Layout &pie = menu->layout->menu_pie();
  transform_orientation_pie_draw(pie, state, ClarityToolID::Rotate, false, true);

  ui::Layout &list = menu->layout->column(false);
  transform_common_list_draw(list, state, "Rotate Options", false);
}

static void clarity_scale_marking_menu_draw(const bContext *C, Menu *menu)
{
  const ClarityMoveToolState state = transform_tool_state_get(C, ClarityToolID::Scale);
  ui::Layout &pie = menu->layout->menu_pie();
  transform_orientation_pie_draw(pie, state, ClarityToolID::Scale, false, false);

  ui::Layout &list = menu->layout->column(false);
  transform_common_list_draw(list, state, "Scale Options", false);
}

static bool clarity_multi_cut_properties_get(const bContext *C, PointerRNA &r_properties)
{
  bToolRef *tool = WM_toolsystem_ref_from_context(C);
  wmOperatorType *knife_type = WM_operatortype_find("MESH_OT_knife_tool", true);
  return tool != nullptr && knife_type != nullptr &&
         WM_toolsystem_ref_properties_get_from_operator(tool, knife_type, &r_properties);
}

static void clarity_multi_cut_marking_menu_draw(const bContext *C, Menu *menu)
{
  PointerRNA properties;
  if (!clarity_multi_cut_properties_get(C, properties)) {
    menu->layout->label("Multi-Cut Tool is not active", ICON_INFO);
    return;
  }

  /* Keep Clarity's directions: W, E, S, N, NW, NE, SW, SE. The native marking-menu path supplies
   * the same compact radius, dead zone and release gesture as the other Clarity tool menus. */
  ui::Layout &pie = menu->layout->menu_pie();
  pie.prop(&properties, "snap_step", UI_ITEM_NONE, "Snap Step %", ICON_NONE);       /* W */
  pie.prop(&properties, "use_edge_flow", UI_ITEM_NONE, "Edge Flow", ICON_NONE);   /* E */
  pie.prop(&properties, "subdivisions", UI_ITEM_NONE, "Subdivisions", ICON_NONE); /* S */
  pie.prop(
      &properties, "ignore_backfaces", UI_ITEM_NONE, "Ignore Backfaces", ICON_NONE); /* N */
  pie.prop(&properties, "delete_faces", UI_ITEM_NONE, "Delete Faces", ICON_NONE);   /* NW */
  pie.prop(&properties, "extract_faces", UI_ITEM_NONE, "Extract Faces", ICON_NONE); /* NE */
  pie.op("MESH_OT_clarity_multi_cut_reset",
         "Reset Tool",
         ICON_LOOP_BACK,
         wm::OpCallContext::ExecDefault,
         UI_ITEM_NONE); /* SW */
  pie.prop(&properties, "use_live_surface", UI_ITEM_NONE, "Live Surface", ICON_NONE); /* SE */
}

/**
 * A submenu of the marking menu is one more panel of it, not a menu in its own right, so it is
 * backed in the same grey as the rows that opened it.
 */
static void clarity_submenu_style_set(Menu *menu)
{
  if (ui::Block *block = menu->layout->block()) {
    ui::block_theme_style_set(block, ui::BLOCK_THEME_STYLE_CLARITY_MENU);
  }
}

static void clarity_camera_based_selection_draw(const bContext *C, Menu *menu)
{
  clarity_submenu_style_set(menu);

  const ClarityCameraBasedSelection active = selection_settings_get(C).camera_based_selection;
  for (const EnumPropertyItem *item = clarity_camera_based_selection_menu_items;
       item->identifier != nullptr;
       item++)
  {
    PointerRNA op_ptr = menu->layout->op("CLARITY_OT_selection_settings_set",
                                         item->name,
                                         check_icon(active == ClarityCameraBasedSelection(item->value)),
                                         wm::OpCallContext::ExecDefault,
                                         UI_ITEM_NONE);
    RNA_enum_set(&op_ptr, "camera_based_selection", item->value);
  }
}

/** The second panel of the selection constraints: what "by angle" means, in degrees. */
static void clarity_selection_constraint_angle_draw(const bContext *C, Menu *menu)
{
  clarity_submenu_style_set(menu);

  /* Only the tolerance. Switching the constraint on is what a click on the Angle row does, so a
   * second switch here would be the same setting under two names. */
  if (wmWindowManager *wm = CTX_wm_manager(C)) {
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    menu->layout->prop(
        &wm_ptr, "clarity_selection_constraint_angle", UI_ITEM_NONE, "Tolerance", ICON_NONE);
  }
}

static void clarity_selection_constraints_draw(const bContext *C, Menu *menu)
{
  clarity_submenu_style_set(menu);

  const ClarityMoveToolState state = move_tool_state_get(C);

  for (const EnumPropertyItem *item = clarity_selection_constraint_items; item->identifier != nullptr;
       item++)
  {
    const ClaritySelectionConstraint constraint = ClaritySelectionConstraint(item->value);
    const int icon = check_icon(state.selection_constraint == constraint);
    PointerRNA op_ptr;
    if (constraint == ClaritySelectionConstraint::Angle) {
      /* Angle is the only constraint that carries a number, and a menu is a stack of full-width
       * rows: anything placed beside a row - a field, an arrow button - pushes everything after it
       * into a second column. So the row stays an ordinary switch and holding it opens the
       * tolerance, the way Clarity's option boxes work. */
      op_ptr = menu->layout->op_menu_hold(
          WM_operatortype_find("CLARITY_OT_selection_constraint_set", true),
          item->name,
          icon,
          wm::OpCallContext::ExecDefault,
          UI_ITEM_NONE,
          "VIEW3D_MT_clarity_selection_constraint_angle");
    }
    else {
      op_ptr = menu->layout->op("CLARITY_OT_selection_constraint_set",
                                item->name,
                                icon,
                                wm::OpCallContext::ExecDefault,
                                UI_ITEM_NONE);
    }
    RNA_enum_set(&op_ptr, "constraint", item->value);
  }
}

static void clarity_transform_constraints_draw(const bContext *C, Menu *menu)
{
  clarity_submenu_style_set(menu);

  const ClarityMoveToolState state = move_tool_state_get(C);
  for (const EnumPropertyItem *item = clarity_transform_constraint_items; item->identifier != nullptr;
       item++)
  {
    const ClarityTransformConstraint constraint = ClarityTransformConstraint(item->value);
    PointerRNA op_ptr = menu->layout->op("CLARITY_OT_transform_constraint_set",
                                         item->name,
                                         check_icon(state.transform_constraint == constraint),
                                         wm::OpCallContext::ExecDefault,
                                         UI_ITEM_NONE);
    RNA_enum_set(&op_ptr, "constraint", item->value);
  }
}

static void marking_menutype_register(const char *idname,
                                      void (*draw)(const bContext *, Menu *),
                                      const bool with_poll)
{
  MenuType *type = MEM_new<MenuType>(__func__);
  STRNCPY_UTF8(type->idname, idname);
  type->draw = draw;
  if (with_poll) {
    type->poll = marking_menu_poll;
  }
  WM_menutype_add(type);
}

void register_marking_menu_types()
{
  WM_operatortype_append(CLARITY_OT_transform_orientation_set);
  WM_operatortype_append(CLARITY_OT_move_option_toggle);
  WM_operatortype_append(CLARITY_OT_selection_constraint_set);
  WM_operatortype_append(CLARITY_OT_transform_constraint_set);
  WM_operatortype_append(CLARITY_OT_tool_options);

  /* Deprecated operator identifiers retained for old keymaps and external scripts. */
#define REGISTER_MAYA_OPERATOR_COMPATIBILITY(name) \
  [](wmOperatorType *ot) { \
    CLARITY_OT_##name(ot); \
    ot->idname = "MAYA_OT_" #name; \
    ot->flag |= OPTYPE_INTERNAL; \
  }
  WM_operatortype_append(REGISTER_MAYA_OPERATOR_COMPATIBILITY(transform_orientation_set));
  WM_operatortype_append(REGISTER_MAYA_OPERATOR_COMPATIBILITY(move_option_toggle));
  WM_operatortype_append(REGISTER_MAYA_OPERATOR_COMPATIBILITY(selection_constraint_set));
  WM_operatortype_append(REGISTER_MAYA_OPERATOR_COMPATIBILITY(transform_constraint_set));
  WM_operatortype_append(REGISTER_MAYA_OPERATOR_COMPATIBILITY(tool_options));
#undef REGISTER_MAYA_OPERATOR_COMPATIBILITY

  marking_menutype_register(
      "VIEW3D_MT_clarity_select_marking_menu", clarity_select_marking_menu_draw, true);
  marking_menutype_register(
      "VIEW3D_MT_clarity_move_marking_menu", clarity_move_marking_menu_draw, true);
  marking_menutype_register(
      "VIEW3D_MT_clarity_rotate_marking_menu", clarity_rotate_marking_menu_draw, true);
  marking_menutype_register(
      "VIEW3D_MT_clarity_scale_marking_menu", clarity_scale_marking_menu_draw, true);
  marking_menutype_register(
      "VIEW3D_MT_clarity_multi_cut_marking_menu", clarity_multi_cut_marking_menu_draw, true);
  marking_menutype_register(
      "VIEW3D_MT_clarity_camera_based_selection", clarity_camera_based_selection_draw, false);
  marking_menutype_register(
      "VIEW3D_MT_clarity_selection_constraints", clarity_selection_constraints_draw, false);
  marking_menutype_register(
      "VIEW3D_MT_clarity_selection_constraint_angle", clarity_selection_constraint_angle_draw, false);
  marking_menutype_register(
      "VIEW3D_MT_clarity_transform_constraints", clarity_transform_constraints_draw, false);

  /* Deprecated menu identifiers retained for old keymaps and external scripts. */
  marking_menutype_register(
      "VIEW3D_MT_maya_select_marking_menu", clarity_select_marking_menu_draw, true);
  marking_menutype_register(
      "VIEW3D_MT_maya_move_marking_menu", clarity_move_marking_menu_draw, true);
  marking_menutype_register(
      "VIEW3D_MT_maya_rotate_marking_menu", clarity_rotate_marking_menu_draw, true);
  marking_menutype_register(
      "VIEW3D_MT_maya_scale_marking_menu", clarity_scale_marking_menu_draw, true);
  marking_menutype_register(
      "VIEW3D_MT_maya_multi_cut_marking_menu", clarity_multi_cut_marking_menu_draw, true);
  marking_menutype_register(
      "VIEW3D_MT_maya_camera_based_selection", clarity_camera_based_selection_draw, false);
  marking_menutype_register(
      "VIEW3D_MT_maya_selection_constraints", clarity_selection_constraints_draw, false);
  marking_menutype_register(
      "VIEW3D_MT_maya_selection_constraint_angle", clarity_selection_constraint_angle_draw, false);
  marking_menutype_register(
      "VIEW3D_MT_maya_transform_constraints", clarity_transform_constraints_draw, false);
}

/** \} */

}  // namespace ed::clarity

bool ED_clarity_move_keep_spacing_get(const bContext *C)
{
  const ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  return runtime == nullptr ? true : runtime->move_tool_settings.keep_spacing;
}

ed::clarity::ClarityTransformConstraint ED_clarity_transform_constraint_get(const bContext *C)
{
  const ed::clarity::ClarityWindowRuntime *runtime = ed::clarity::runtime_get(C);
  return runtime == nullptr ? ed::clarity::ClarityTransformConstraint::Off :
                              runtime->move_tool_settings.transform_constraint;
}

}  // namespace blender
