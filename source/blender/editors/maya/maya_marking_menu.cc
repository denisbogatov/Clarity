/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 *
 * The Maya Move Tool marking menu, its submenus and the state behind them.
 */

#include "maya_marking_menu.hh"

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
#include "WM_types.hh"

#include "maya_runtime.hh"

namespace blender {
namespace ed::maya {

/* -------------------------------------------------------------------- */
/** \name State
 *
 * Every setting is read from whoever really owns it. Four of them are Blender's own and are
 * reachable from other parts of the interface, so the menu must not keep a copy: it would be a
 * second truth that silently disagrees the moment the user changes one of them elsewhere.
 * \{ */

static TransformOrientationSlot *move_orientation_slot_get(const bContext *C)
{
  Scene *scene = CTX_data_scene(C);
  if (scene == nullptr) {
    return nullptr;
  }
  return BKE_scene_orientation_slot_get(scene, SCE_ORIENT_TRANSLATE);
}

static MayaMoveOrientation move_orientation_from_blender(const int orientation_type)
{
  switch (orientation_type) {
    case V3D_ORIENT_LOCAL:
      return MayaMoveOrientation::Object;
    case V3D_ORIENT_NORMAL:
      return MayaMoveOrientation::Component;
    default:
      return MayaMoveOrientation::World;
  }
}

static int move_orientation_to_blender(const MayaMoveOrientation orientation)
{
  switch (orientation) {
    case MayaMoveOrientation::Object:
      return V3D_ORIENT_LOCAL;
    case MayaMoveOrientation::Component:
      /* Maya builds the frame from the normals of the selected components and falls back to the
       * object's own axes for a whole object, which is what Blender's Normal orientation does. */
      return V3D_ORIENT_NORMAL;
    case MayaMoveOrientation::World:
      break;
  }
  return V3D_ORIENT_GLOBAL;
}

MayaMoveToolState move_tool_state_get(const bContext *C)
{
  MayaMoveToolState state;

  if (const TransformOrientationSlot *slot = move_orientation_slot_get(C)) {
    state.orientation = move_orientation_from_blender(
        BKE_scene_orientation_slot_get_index(slot));
  }

  if (const ToolSettings *ts = CTX_data_tool_settings(C)) {
    state.preserve_uvs = (ts->uvcalc_flag & UVCALC_TRANSFORM_CORRECT) != 0;
    state.preserve_children = (ts->transform_flag & SCE_XFORM_SKIP_CHILDREN) != 0;
  }

  if (const MayaWindowRuntime *runtime = runtime_get(C)) {
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

bool move_option_get(const MayaMoveToolState &state, const MayaMoveOption option)
{
  switch (option) {
    case MayaMoveOption::KeepSpacing:
      return state.keep_spacing;
    case MayaMoveOption::ShiftExtrude:
      return state.shift_extrude;
    case MayaMoveOption::ShiftDuplicate:
      return state.shift_duplicate;
    case MayaMoveOption::PreserveUVs:
      return state.preserve_uvs;
    case MayaMoveOption::PreserveChildren:
      return state.preserve_children;
    case MayaMoveOption::TweakMode:
      return state.tweak_mode;
    case MayaMoveOption::UpdateTriad:
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

bool move_option_set(bContext *C, const MayaMoveOption option, const bool value)
{
  switch (option) {
    case MayaMoveOption::PreserveUVs:
    case MayaMoveOption::PreserveChildren: {
      ToolSettings *ts = CTX_data_tool_settings(C);
      if (ts == nullptr) {
        return false;
      }
      if (option == MayaMoveOption::PreserveUVs) {
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

  MayaWindowRuntime *runtime = runtime_ensure(C);
  if (runtime == nullptr) {
    return false;
  }
  switch (option) {
    case MayaMoveOption::KeepSpacing:
      runtime->move_tool_settings.keep_spacing = value;
      break;
    case MayaMoveOption::ShiftExtrude:
      runtime->selection_settings.shift_extrude = value;
      break;
    case MayaMoveOption::ShiftDuplicate:
      runtime->selection_settings.shift_duplicate = value;
      break;
    case MayaMoveOption::TweakMode:
      runtime->move_tool_settings.tweak_mode = value;
      break;
    case MayaMoveOption::UpdateTriad:
      runtime->move_tool_settings.update_triad = value;
      break;
    case MayaMoveOption::PreserveUVs:
    case MayaMoveOption::PreserveChildren:
      BLI_assert_unreachable();
      return false;
  }
  move_menu_state_changed(C, false);
  return true;
}

bool move_orientation_set(bContext *C, const MayaMoveOrientation orientation)
{
  TransformOrientationSlot *slot = move_orientation_slot_get(C);
  if (slot == nullptr) {
    return false;
  }
  BKE_scene_orientation_slot_set_index(slot, move_orientation_to_blender(orientation));
  move_menu_state_changed(C, true);
  return true;
}

bool selection_constraint_set(bContext *C, const MayaSelectionConstraint constraint)
{
  MayaWindowRuntime *runtime = runtime_ensure(C);
  if (runtime == nullptr) {
    return false;
  }
  runtime->selection_settings.selection_constraint = constraint;
  move_menu_state_changed(C, false);
  return true;
}

bool transform_constraint_set(bContext *C, const MayaTransformConstraint constraint)
{
  MayaWindowRuntime *runtime = runtime_ensure(C);
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

static const EnumPropertyItem maya_move_orientation_items[] = {
    {int(MayaMoveOrientation::Object),
     "OBJECT",
     0,
     "Object",
     "Orient the manipulator along the local axes of each selected object"},
    {int(MayaMoveOrientation::World),
     "WORLD",
     0,
     "World",
     "Orient the manipulator along the global axes of the scene"},
    {int(MayaMoveOrientation::Component),
     "COMPONENT",
     0,
     "Component",
     "Orient the manipulator along the averaged frame of the selected components"},
    {0, nullptr, 0, nullptr, nullptr},
};

static const EnumPropertyItem maya_move_option_items[] = {
    {int(MayaMoveOption::KeepSpacing),
     "KEEP_SPACING",
     0,
     "Keep Spacing",
     "Move the whole selection to the snap target as one instead of snapping it element by "
     "element"},
    {int(MayaMoveOption::ShiftExtrude),
     "SHIFT_EXTRUDE",
     0,
     "Shift Extrude",
     "Let a Shift drag of the manipulator extrude the selected components"},
    {int(MayaMoveOption::ShiftDuplicate),
     "SHIFT_DUPLICATE",
     0,
     "Shift Duplicate",
     "Let a Shift drag of the manipulator duplicate the selected objects"},
    {int(MayaMoveOption::PreserveUVs),
     "PRESERVE_UVS",
     0,
     "Preserve UVs",
     "Correct the UVs of moved geometry so the texture keeps its placement"},
    {int(MayaMoveOption::PreserveChildren),
     "PRESERVE_CHILDREN",
     0,
     "Preserve Children",
     "Keep children in place when their parent is moved"},
    {int(MayaMoveOption::TweakMode),
     "TWEAK_MODE",
     0,
     "Tweak Mode",
     "Hide the manipulator and select-and-drag the component under the pointer directly"},
    {int(MayaMoveOption::UpdateTriad),
     "UPDATE_TRIAD",
     0,
     "Update Triad",
     "Recompute the component orientation of the manipulator while the drag is running"},
    {0, nullptr, 0, nullptr, nullptr},
};

static const EnumPropertyItem maya_selection_constraint_items[] = {
    {int(MayaSelectionConstraint::Off), "OFF", 0, "Off", "Select components without any constraint"},
    {int(MayaSelectionConstraint::Angle),
     "ANGLE",
     0,
     "Angle",
     "Grow the selection over connected components that stay inside an angle tolerance"},
    {int(MayaSelectionConstraint::Border),
     "BORDER",
     0,
     "Border",
     "Grow the selection along the open border of the mesh"},
    {int(MayaSelectionConstraint::EdgeLoop),
     "EDGE_LOOP",
     0,
     "Edge Loop",
     "Select the edge loop the picked edge belongs to"},
    {int(MayaSelectionConstraint::EdgeRing),
     "EDGE_RING",
     0,
     "Edge Ring",
     "Select the edge ring the picked edge belongs to"},
    {int(MayaSelectionConstraint::Shell),
     "SHELL",
     0,
     "Shell",
     "Grow the selection over the whole connected island of the mesh"},
    {0, nullptr, 0, nullptr, nullptr},
};

static const EnumPropertyItem maya_transform_constraint_items[] = {
    {int(MayaTransformConstraint::Off), "OFF", 0, "Off", "Move components freely"},
    {int(MayaTransformConstraint::Edge),
     "EDGE",
     0,
     "Edge Slide",
     "Keep moved components on the edges they started on"},
    {int(MayaTransformConstraint::Surface),
     "SURFACE",
     0,
     "Surface Slide",
     "Keep moved components on the surface of the mesh"},
    {0, nullptr, 0, nullptr, nullptr},
};

static wmOperatorStatus maya_move_orientation_set_exec(bContext *C, wmOperator *op)
{
  const MayaMoveOrientation orientation = MayaMoveOrientation(
      RNA_enum_get(op->ptr, "orientation"));
  return move_orientation_set(C, orientation) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static void MAYA_OT_move_orientation_set(wmOperatorType *ot)
{
  ot->name = "Maya Move Orientation";
  ot->description = "Set the coordinate system the Move Tool manipulator is oriented in";
  ot->idname = "MAYA_OT_move_orientation_set";
  ot->exec = maya_move_orientation_set_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_enum(ot->srna,
               "orientation",
               maya_move_orientation_items,
               int(MayaMoveOrientation::World),
               "Orientation",
               "");
}

static wmOperatorStatus maya_move_option_toggle_exec(bContext *C, wmOperator *op)
{
  const MayaMoveOption option = MayaMoveOption(RNA_enum_get(op->ptr, "option"));
  /* The menu never tells the operator what to write: the toggle flips whatever the setting is at
   * the moment it runs, so a shortcut and a menu item can never disagree about the new value. */
  const bool value = !move_option_get(move_tool_state_get(C), option);
  return move_option_set(C, option, value) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static void MAYA_OT_move_option_toggle(wmOperatorType *ot)
{
  ot->name = "Maya Move Option";
  ot->description = "Toggle one independent option of the Maya Move Tool";
  ot->idname = "MAYA_OT_move_option_toggle";
  ot->exec = maya_move_option_toggle_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER;

  RNA_def_enum(ot->srna,
               "option",
               maya_move_option_items,
               int(MayaMoveOption::KeepSpacing),
               "Option",
               "");
}

static wmOperatorStatus maya_selection_constraint_set_exec(bContext *C, wmOperator *op)
{
  const MayaSelectionConstraint constraint = MayaSelectionConstraint(
      RNA_enum_get(op->ptr, "constraint"));
  return selection_constraint_set(C, constraint) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static void MAYA_OT_selection_constraint_set(wmOperatorType *ot)
{
  ot->name = "Maya Selection Constraint";
  ot->description = "Set how a component selection is filtered and grown";
  ot->idname = "MAYA_OT_selection_constraint_set";
  ot->exec = maya_selection_constraint_set_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER;

  RNA_def_enum(ot->srna,
               "constraint",
               maya_selection_constraint_items,
               int(MayaSelectionConstraint::Off),
               "Constraint",
               "");
}

static wmOperatorStatus maya_transform_constraint_set_exec(bContext *C, wmOperator *op)
{
  const MayaTransformConstraint constraint = MayaTransformConstraint(
      RNA_enum_get(op->ptr, "constraint"));
  return transform_constraint_set(C, constraint) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static void MAYA_OT_transform_constraint_set(wmOperatorType *ot)
{
  ot->name = "Maya Transform Constraint";
  ot->description = "Constrain moved components to the geometry of the active mesh";
  ot->idname = "MAYA_OT_transform_constraint_set";
  ot->exec = maya_transform_constraint_set_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER;

  RNA_def_enum(ot->srna,
               "constraint",
               maya_transform_constraint_items,
               int(MayaTransformConstraint::Off),
               "Constraint",
               "");
}

static wmOperatorStatus maya_move_options_exec(bContext *C, wmOperator * /*op*/)
{
  /* Maya's Move Options opens the Tool Settings of the active tool. The sidebar Tool tab is where
   * this fork keeps them, so the command only has to make sure it is the visible one. */
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

static void MAYA_OT_move_options(wmOperatorType *ot)
{
  ot->name = "Maya Move Options";
  ot->description = "Show the settings of the active Move Tool";
  ot->idname = "MAYA_OT_move_options";
  ot->exec = maya_move_options_exec;
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
  /* Maya marks an active toggle or the live entry of an exclusive group with a check, and leaves
   * the blue highlight to mean "under the pointer" alone. */
  return active ? ICON_CHECKBOX_HLT : ICON_CHECKBOX_DEHLT;
}

static void orientation_item(ui::Layout &layout,
                             const MayaMoveToolState &state,
                             const char *name,
                             const MayaMoveOrientation orientation)
{
  PointerRNA op_ptr = layout.op("MAYA_OT_move_orientation_set",
                                name,
                                check_icon(state.orientation == orientation),
                                wm::OpCallContext::ExecDefault,
                                UI_ITEM_NONE);
  RNA_enum_set(&op_ptr, "orientation", int(orientation));
}

static void option_item(ui::Layout &layout,
                        const MayaMoveToolState &state,
                        const char *name,
                        const MayaMoveOption option)
{
  PointerRNA op_ptr = layout.op("MAYA_OT_move_option_toggle",
                                name,
                                check_icon(move_option_get(state, option)),
                                wm::OpCallContext::ExecDefault,
                                UI_ITEM_NONE);
  RNA_enum_set(&op_ptr, "option", int(option));
}

static void maya_move_marking_menu_draw(const bContext *C, Menu *menu)
{
  const MayaMoveToolState state = move_tool_state_get(C);

  /* Blender fills the eight radial slots in the order W, E, S, N, NW, NE, SW, SE. The empty ones
   * are the four entries of Maya's own menu this fork does not implement yet, and a separator is
   * how a slot is left free without shifting everything after it. */
  ui::Layout &pie = menu->layout->menu_pie();
  orientation_item(pie, state, "World", MayaMoveOrientation::World); /* W */
  pie.separator();                                                   /* E */
  pie.separator();                                                   /* S */
  pie.separator();                                                   /* N */
  orientation_item(pie, state, "Object", MayaMoveOrientation::Object);       /* NW */
  orientation_item(pie, state, "Component", MayaMoveOrientation::Component); /* NE */
  pie.separator();                                                          /* SW */
  option_item(pie, state, "Keep Spacing", MayaMoveOption::KeepSpacing);      /* SE */

  /* The linear part hangs under the wheel, exactly like Maya's. The blank icon puts the two
   * submenu rows in the same column as the checks, so the list reads as one stack of buttons. */
  ui::Layout &list = menu->layout->column(false);
  list.menu("VIEW3D_MT_maya_selection_constraints", "Selection Constraints", ICON_BLANK1);
  list.menu("VIEW3D_MT_maya_transform_constraints", "Transform Constraints", ICON_BLANK1);
  list.separator();
  option_item(list, state, "Shift Extrude", MayaMoveOption::ShiftExtrude);
  option_item(list, state, "Shift Duplicate", MayaMoveOption::ShiftDuplicate);
  option_item(list, state, "Preserve UVs", MayaMoveOption::PreserveUVs);
  option_item(list, state, "Preserve Children", MayaMoveOption::PreserveChildren);
  option_item(list, state, "Tweak Mode", MayaMoveOption::TweakMode);
  option_item(list, state, "Update Triad", MayaMoveOption::UpdateTriad);
  list.separator();
  /* An action, not a state, so it carries no check. */
  list.op("MAYA_OT_move_options",
          "Move Options",
          ICON_BLANK1,
          wm::OpCallContext::ExecDefault,
          UI_ITEM_NONE);
}

/**
 * A submenu of the marking menu is one more panel of it, not a menu in its own right, so it is
 * backed in the same grey as the rows that opened it.
 */
static void maya_submenu_style_set(Menu *menu)
{
  if (ui::Block *block = menu->layout->block()) {
    ui::block_theme_style_set(block, ui::BLOCK_THEME_STYLE_MAYA_MENU);
  }
}

/** The second panel of the selection constraints: what "by angle" means, in degrees. */
static void maya_selection_constraint_angle_draw(const bContext *C, Menu *menu)
{
  maya_submenu_style_set(menu);

  /* Only the tolerance. Switching the constraint on is what a click on the Angle row does, so a
   * second switch here would be the same setting under two names. */
  if (wmWindowManager *wm = CTX_wm_manager(C)) {
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    menu->layout->prop(
        &wm_ptr, "maya_selection_constraint_angle", UI_ITEM_NONE, "Tolerance", ICON_NONE);
  }
}

static void maya_selection_constraints_draw(const bContext *C, Menu *menu)
{
  maya_submenu_style_set(menu);

  const MayaMoveToolState state = move_tool_state_get(C);

  for (const EnumPropertyItem *item = maya_selection_constraint_items; item->identifier != nullptr;
       item++)
  {
    const MayaSelectionConstraint constraint = MayaSelectionConstraint(item->value);
    const int icon = check_icon(state.selection_constraint == constraint);
    PointerRNA op_ptr;
    if (constraint == MayaSelectionConstraint::Angle) {
      /* Angle is the only constraint that carries a number, and a menu is a stack of full-width
       * rows: anything placed beside a row - a field, an arrow button - pushes everything after it
       * into a second column. So the row stays an ordinary switch and holding it opens the
       * tolerance, the way Maya's option boxes work. */
      op_ptr = menu->layout->op_menu_hold(
          WM_operatortype_find("MAYA_OT_selection_constraint_set", true),
          item->name,
          icon,
          wm::OpCallContext::ExecDefault,
          UI_ITEM_NONE,
          "VIEW3D_MT_maya_selection_constraint_angle");
    }
    else {
      op_ptr = menu->layout->op("MAYA_OT_selection_constraint_set",
                                item->name,
                                icon,
                                wm::OpCallContext::ExecDefault,
                                UI_ITEM_NONE);
    }
    RNA_enum_set(&op_ptr, "constraint", item->value);
  }
}

static void maya_transform_constraints_draw(const bContext *C, Menu *menu)
{
  maya_submenu_style_set(menu);

  const MayaMoveToolState state = move_tool_state_get(C);
  for (const EnumPropertyItem *item = maya_transform_constraint_items; item->identifier != nullptr;
       item++)
  {
    const MayaTransformConstraint constraint = MayaTransformConstraint(item->value);
    PointerRNA op_ptr = menu->layout->op("MAYA_OT_transform_constraint_set",
                                         item->name,
                                         check_icon(state.transform_constraint == constraint),
                                         wm::OpCallContext::ExecDefault,
                                         UI_ITEM_NONE);
    RNA_enum_set(&op_ptr, "constraint", item->value);
  }
}

static void move_menutype_register(const char *idname,
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
  WM_operatortype_append(MAYA_OT_move_orientation_set);
  WM_operatortype_append(MAYA_OT_move_option_toggle);
  WM_operatortype_append(MAYA_OT_selection_constraint_set);
  WM_operatortype_append(MAYA_OT_transform_constraint_set);
  WM_operatortype_append(MAYA_OT_move_options);

  move_menutype_register("VIEW3D_MT_maya_move_marking_menu", maya_move_marking_menu_draw, true);
  move_menutype_register(
      "VIEW3D_MT_maya_selection_constraints", maya_selection_constraints_draw, false);
  move_menutype_register(
      "VIEW3D_MT_maya_selection_constraint_angle", maya_selection_constraint_angle_draw, false);
  move_menutype_register(
      "VIEW3D_MT_maya_transform_constraints", maya_transform_constraints_draw, false);
}

/** \} */

}  // namespace ed::maya

bool ED_maya_move_keep_spacing_get(const bContext *C)
{
  const ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  return runtime == nullptr ? true : runtime->move_tool_settings.keep_spacing;
}

ed::maya::MayaTransformConstraint ED_maya_transform_constraint_get(const bContext *C)
{
  const ed::maya::MayaWindowRuntime *runtime = ed::maya::runtime_get(C);
  return runtime == nullptr ? ed::maya::MayaTransformConstraint::Off :
                              runtime->move_tool_settings.transform_constraint;
}

}  // namespace blender
