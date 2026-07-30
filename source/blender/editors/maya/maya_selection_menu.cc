/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 *
 * The Maya polygon component selection marking menu.
 *
 * Every entry is one command with no state of its own, so the only thing the menu has to decide is
 * whether a command can run at all on what is selected right now. That decision lives in
 * #selection_command_enabled, next to the query it reads, because a greyed entry and an entry that
 * runs and produces nothing are the same bug seen from two sides.
 */

#include "maya_selection_menu.hh"

#include <functional>

#include "MEM_guardedalloc.h"

#include "DNA_mesh_types.h"
#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "BLI_string.h"
#include "BLI_string_utf8.h"

#include "BKE_context.hh"
#include "BKE_customdata.hh"
#include "BKE_editmesh.hh"
#include "BKE_screen.hh"

#include "ED_screen.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "UI_interface_c.hh"
#include "UI_interface_layout.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "bmesh.hh"

#include "maya_marking_menu.hh"
#include "maya_runtime.hh"

namespace blender {
namespace ed::maya {

/* -------------------------------------------------------------------- */
/** \name What the selection can be asked for
 * \{ */

MayaSelectionMenuContext selection_menu_context_get(const bContext *C)
{
  MayaSelectionMenuContext context;

  const Object *object = CTX_data_edit_object(C);
  if (object == nullptr || object->type != OB_MESH) {
    return context;
  }
  const BMEditMesh *em = BKE_editmesh_from_object(const_cast<Object *>(object));
  if (em == nullptr || em->bm == nullptr) {
    return context;
  }
  BMesh &bm = *em->bm;

  context.object_is_mesh = true;
  context.selected_vert_num = bm.totvertsel;
  context.selected_edge_num = bm.totedgesel;
  context.selected_face_num = bm.totfacesel;
  context.has_selection = (bm.totvertsel + bm.totedgesel + bm.totfacesel) > 0;
  context.has_uv_layer = CustomData_has_layer(&bm.ldata, CD_PROP_FLOAT2);

  if (const MayaWindowRuntime *runtime = runtime_get(C)) {
    context.component_mode = runtime->component_mode;
    context.selection_constraint = runtime->selection_settings.selection_constraint;
  }

  /* Loops and rings walk from edges, and every selection that has a vertex or a face in it can be
   * turned into edges first, which is what Maya does before it walks. */
  context.supports_edge_loop = context.has_selection;
  context.supports_edge_ring = context.has_selection;

  if (bm.totedgesel > 0) {
    BMIter iter;
    BMEdge *edge;
    BM_ITER_MESH (edge, &iter, &bm, BM_EDGES_OF_MESH) {
      if (BM_elem_flag_test(edge, BM_ELEM_SELECT) && BM_edge_is_boundary(edge)) {
        context.has_border_edges = true;
        break;
      }
    }
  }

  return context;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Commands
 * \{ */

bool selection_command_enabled(const MayaSelectionMenuContext &context,
                               const MayaSelectionCommand command)
{
  if (!context.object_is_mesh) {
    /* Only the constraint settings survive without a component selection to work on. */
    return false;
  }

  switch (command) {
    /* Conversions and propagation all need something selected. */
    case MayaSelectionCommand::ToVertices:
    case MayaSelectionCommand::ToEdges:
    case MayaSelectionCommand::ToContainedEdges:
    case MayaSelectionCommand::ToFaces:
    case MayaSelectionCommand::ToContainedFaces:
    case MayaSelectionCommand::Grow:
    case MayaSelectionCommand::Shrink:
      return context.has_selection;

    /* A perimeter is only defined for an area, so Maya derives it from a face region. */
    case MayaSelectionCommand::ToVertexPerimeter:
    case MayaSelectionCommand::ToEdgePerimeter:
    case MayaSelectionCommand::ToFacePerimeter:
    case MayaSelectionCommand::SelectionBoundary:
      return context.selected_face_num > 0;

    case MayaSelectionCommand::ToEdgeLoop:
    case MayaSelectionCommand::ToEdgeLoopAndDuplicate:
    case MayaSelectionCommand::ToEdgeLoopAndDelete:
      return context.supports_edge_loop;

    case MayaSelectionCommand::ToEdgeRing:
    case MayaSelectionCommand::ToEdgeRingAndSplit:
    case MayaSelectionCommand::ToEdgeRingAndCollapse:
      return context.supports_edge_ring;

    case MayaSelectionCommand::ToUVs:
      return context.has_selection && context.has_uv_layer;

    /* No backend in this fork yet. Maya greys out what it cannot do instead of running it and
     * leaving the user to guess what happened, and so does this. */
    case MayaSelectionCommand::ToUVPerimeter:
    case MayaSelectionCommand::ToUVEdgeLoop:
    case MayaSelectionCommand::ToUVShell:
    case MayaSelectionCommand::ToShell:
    case MayaSelectionCommand::ToShellBorder:
    case MayaSelectionCommand::ToFacePath:
    case MayaSelectionCommand::GrowAlongLoop:
    case MayaSelectionCommand::ShrinkAlongLoop:
    case MayaSelectionCommand::SelectEdgeLoopTool:
    case MayaSelectionCommand::SelectEdgeRingTool:
    case MayaSelectionCommand::SelectBorderEdgeTool:
      return false;
  }
  return false;
}

/** Component type a conversion leaves behind, so the Maya component mode can follow it. */
static MayaComponentMode command_result_component_mode(const MayaSelectionCommand command)
{
  switch (command) {
    case MayaSelectionCommand::ToVertices:
    case MayaSelectionCommand::ToVertexPerimeter:
      return MayaComponentMode::Vertex;
    case MayaSelectionCommand::ToEdges:
    case MayaSelectionCommand::ToContainedEdges:
    case MayaSelectionCommand::ToEdgePerimeter:
    case MayaSelectionCommand::ToEdgeLoop:
    case MayaSelectionCommand::ToEdgeRing:
    case MayaSelectionCommand::SelectionBoundary:
      return MayaComponentMode::Edge;
    case MayaSelectionCommand::ToFaces:
    case MayaSelectionCommand::ToContainedFaces:
    case MayaSelectionCommand::ToFacePerimeter:
      return MayaComponentMode::Face;
    case MayaSelectionCommand::ToUVs:
      return MayaComponentMode::UV;
    default:
      break;
  }
  return MayaComponentMode::Object;
}

static wmOperatorStatus operator_call(bContext *C,
                                      const char *idname,
                                      const std::function<void(PointerRNA &)> &fill_properties)
{
  wmOperatorType *ot = WM_operatortype_find(idname, true);
  if (ot == nullptr) {
    return OPERATOR_CANCELLED;
  }
  if (!fill_properties) {
    return WM_operator_name_call_ptr(C, ot, wm::OpCallContext::ExecDefault, nullptr, nullptr);
  }
  PointerRNA ptr = WM_operator_properties_create_ptr(ot);
  fill_properties(ptr);
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::ExecDefault, &ptr, nullptr);
  WM_operator_properties_free(&ptr);
  return status;
}

/** The component type a select mode mask resolves to, the way Blender's own conversion reads it. */
static int select_mode_highest(const int select_bits)
{
  if (select_bits & SCE_SELECT_FACE) {
    return SCE_SELECT_FACE;
  }
  if (select_bits & SCE_SELECT_EDGE) {
    return SCE_SELECT_EDGE;
  }
  return SCE_SELECT_VERTEX;
}

/**
 * Convert the selection to \a target_bits.
 *
 * \a permissive is Maya's plain `To X`: everything the selection touches. Off, it is `To Contained
 * X`: only what the selection fully covers.
 *
 * The `use_expand` this ends up passing is not the same idea in both directions. Going up it means
 * "any", against a default of "all"; going down it means "only what is completely surrounded",
 * against a default of "everything below the selection". So the permissive answer is `expand` on
 * the way up and no `expand` on the way down, and the contained answer is the other way around.
 * Asking for expand in both directions is what turned a single selected face into nothing at all:
 * no vertex of one face is surrounded by selected faces.
 */
static wmOperatorStatus select_mode_convert_call(bContext *C,
                                                 const int target_bits,
                                                 const bool permissive)
{
  Object *object = CTX_data_edit_object(C);
  const BMEditMesh *em = object != nullptr ? BKE_editmesh_from_object(object) : nullptr;
  if (em == nullptr) {
    return OPERATOR_CANCELLED;
  }
  const bool flush_up = target_bits > select_mode_highest(em->selectmode);
  const bool expand = permissive ? flush_up : !flush_up;

  return operator_call(C, "MESH_OT_select_mode", [&](PointerRNA &ptr) {
    RNA_boolean_set(&ptr, "use_extend", false);
    RNA_boolean_set(&ptr, "use_expand", expand);
    RNA_enum_set(&ptr, "type", target_bits);
  });
}

static wmOperatorStatus loop_or_ring_call(bContext *C, const bool ring)
{
  /* Both walkers start from edges, so a vertex or face selection is converted first, exactly like
   * Maya converts before it walks a loop or a ring. */
  select_mode_convert_call(C, SCE_SELECT_EDGE, true);
  return operator_call(
      C, ring ? "MESH_OT_select_edge_ring_multi" : "MESH_OT_select_edge_loop_multi", nullptr);
}

static wmOperatorStatus selection_command_execute(bContext *C, const MayaSelectionCommand command)
{
  switch (command) {
    case MayaSelectionCommand::ToVertices:
      return select_mode_convert_call(C, SCE_SELECT_VERTEX, true);
    case MayaSelectionCommand::ToEdges:
      return select_mode_convert_call(C, SCE_SELECT_EDGE, true);
    case MayaSelectionCommand::ToContainedEdges:
      return select_mode_convert_call(C, SCE_SELECT_EDGE, false);
    case MayaSelectionCommand::ToFaces:
      return select_mode_convert_call(C, SCE_SELECT_FACE, true);
    case MayaSelectionCommand::ToContainedFaces:
      return select_mode_convert_call(C, SCE_SELECT_FACE, false);

    case MayaSelectionCommand::ToEdgePerimeter:
    case MayaSelectionCommand::SelectionBoundary:
      return operator_call(C, "MESH_OT_region_to_loop", nullptr);
    case MayaSelectionCommand::ToVertexPerimeter:
      operator_call(C, "MESH_OT_region_to_loop", nullptr);
      return select_mode_convert_call(C, SCE_SELECT_VERTEX, true);
    case MayaSelectionCommand::ToFacePerimeter:
      operator_call(C, "MESH_OT_region_to_loop", nullptr);
      return select_mode_convert_call(C, SCE_SELECT_FACE, true);

    case MayaSelectionCommand::ToUVs:
      return operator_call(C, "MAYA_OT_component_mode_set", [](PointerRNA &ptr) {
        RNA_enum_set(&ptr, "mode", int(MayaComponentMode::UV));
      });

    case MayaSelectionCommand::Grow:
      return operator_call(C, "MESH_OT_select_more", [](PointerRNA &ptr) {
        RNA_boolean_set(&ptr, "use_face_step", true);
      });
    case MayaSelectionCommand::Shrink:
      return operator_call(C, "MESH_OT_select_less", [](PointerRNA &ptr) {
        RNA_boolean_set(&ptr, "use_face_step", true);
      });

    case MayaSelectionCommand::ToEdgeLoop:
      return loop_or_ring_call(C, false);
    case MayaSelectionCommand::ToEdgeRing:
      return loop_or_ring_call(C, true);

    case MayaSelectionCommand::ToEdgeRingAndSplit:
      loop_or_ring_call(C, true);
      /* Subdividing a ring is what inserts the connecting sequence Maya's `polySplitRing` adds. */
      return operator_call(C, "MESH_OT_subdivide", [](PointerRNA &ptr) {
        RNA_int_set(&ptr, "number_cuts", 1);
      });
    case MayaSelectionCommand::ToEdgeRingAndCollapse:
      loop_or_ring_call(C, true);
      return operator_call(C, "MESH_OT_edge_collapse", nullptr);
    case MayaSelectionCommand::ToEdgeLoopAndDuplicate:
      loop_or_ring_call(C, false);
      return operator_call(C, "MESH_OT_offset_edge_loops", nullptr);
    case MayaSelectionCommand::ToEdgeLoopAndDelete:
      loop_or_ring_call(C, false);
      /* `polyDelEdge -cleanVertices true`: the vertices the removed edges leave behind go too. */
      return operator_call(C, "MESH_OT_dissolve_edges", [](PointerRNA &ptr) {
        RNA_boolean_set(&ptr, "use_verts", true);
        RNA_boolean_set(&ptr, "use_face_split", false);
      });

    case MayaSelectionCommand::ToUVPerimeter:
    case MayaSelectionCommand::ToUVEdgeLoop:
    case MayaSelectionCommand::ToUVShell:
    case MayaSelectionCommand::ToShell:
    case MayaSelectionCommand::ToShellBorder:
    case MayaSelectionCommand::ToFacePath:
    case MayaSelectionCommand::GrowAlongLoop:
    case MayaSelectionCommand::ShrinkAlongLoop:
    case MayaSelectionCommand::SelectEdgeLoopTool:
    case MayaSelectionCommand::SelectEdgeRingTool:
    case MayaSelectionCommand::SelectBorderEdgeTool:
      break;
  }
  return OPERATOR_CANCELLED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operator
 * \{ */

#define MAYA_SELECTION_COMMAND(id, identifier, name, description) \
  {int(MayaSelectionCommand::id), identifier, 0, name, description},

static const EnumPropertyItem maya_selection_command_items[] = {
    MAYA_SELECTION_COMMAND(ToVertices, "TO_VERTICES", "To Vertices", "")
    MAYA_SELECTION_COMMAND(ToVertexPerimeter, "TO_VERTEX_PERIMETER", "To Vertex Perimeter", "")
    MAYA_SELECTION_COMMAND(ToEdges, "TO_EDGES", "To Edges", "")
    MAYA_SELECTION_COMMAND(ToContainedEdges, "TO_CONTAINED_EDGES", "To Contained Edges", "")
    MAYA_SELECTION_COMMAND(ToEdgePerimeter, "TO_EDGE_PERIMETER", "To Edge Perimeter", "")
    MAYA_SELECTION_COMMAND(ToFaces, "TO_FACES", "To Faces", "")
    MAYA_SELECTION_COMMAND(ToContainedFaces, "TO_CONTAINED_FACES", "To Contained Faces", "")
    MAYA_SELECTION_COMMAND(ToFacePerimeter, "TO_FACE_PERIMETER", "To Face Perimeter", "")
    MAYA_SELECTION_COMMAND(ToUVs, "TO_UVS", "To UVs", "")
    MAYA_SELECTION_COMMAND(ToUVPerimeter, "TO_UV_PERIMETER", "To UV Perimeter", "")
    MAYA_SELECTION_COMMAND(ToUVEdgeLoop, "TO_UV_EDGE_LOOP", "To UV Edge Loop", "")
    MAYA_SELECTION_COMMAND(Grow, "GROW", "Grow", "")
    MAYA_SELECTION_COMMAND(GrowAlongLoop, "GROW_ALONG_LOOP", "Grow Along Loop", "")
    MAYA_SELECTION_COMMAND(Shrink, "SHRINK", "Shrink", "")
    MAYA_SELECTION_COMMAND(ShrinkAlongLoop, "SHRINK_ALONG_LOOP", "Shrink Along Loop", "")
    MAYA_SELECTION_COMMAND(ToEdgeRing, "TO_EDGE_RING", "To Edge Ring", "")
    MAYA_SELECTION_COMMAND(SelectEdgeRingTool, "SELECT_EDGE_RING_TOOL", "Select Edge Ring Tool", "")
    MAYA_SELECTION_COMMAND(
        ToEdgeRingAndSplit, "TO_EDGE_RING_AND_SPLIT", "To Edge Ring and Split", "")
    MAYA_SELECTION_COMMAND(
        ToEdgeRingAndCollapse, "TO_EDGE_RING_AND_COLLAPSE", "To Edge Ring and Collapse", "")
    MAYA_SELECTION_COMMAND(ToEdgeLoop, "TO_EDGE_LOOP", "To Edge Loop", "")
    MAYA_SELECTION_COMMAND(SelectEdgeLoopTool, "SELECT_EDGE_LOOP_TOOL", "Select Edge Loop Tool", "")
    MAYA_SELECTION_COMMAND(
        ToEdgeLoopAndDuplicate, "TO_EDGE_LOOP_AND_DUPLICATE", "To Edge Loop and Duplicate", "")
    MAYA_SELECTION_COMMAND(
        ToEdgeLoopAndDelete, "TO_EDGE_LOOP_AND_DELETE", "To Edge Loop and Delete", "")
    MAYA_SELECTION_COMMAND(ToFacePath, "TO_FACE_PATH", "To Face Path", "")
    MAYA_SELECTION_COMMAND(ToUVShell, "TO_UV_SHELL", "To UV Shell", "")
    MAYA_SELECTION_COMMAND(ToShell, "TO_SHELL", "To Shell", "")
    MAYA_SELECTION_COMMAND(ToShellBorder, "TO_SHELL_BORDER", "To Shell Border", "")
    MAYA_SELECTION_COMMAND(
        SelectBorderEdgeTool, "SELECT_BORDER_EDGE_TOOL", "Select Border Edge Tool", "")
    MAYA_SELECTION_COMMAND(SelectionBoundary, "SELECTION_BOUNDARY", "Selection Boundary", "")
        {0, nullptr, 0, nullptr, nullptr},
};

#undef MAYA_SELECTION_COMMAND

static wmOperatorStatus maya_selection_command_exec(bContext *C, wmOperator *op)
{
  const MayaSelectionCommand command = MayaSelectionCommand(RNA_enum_get(op->ptr, "command"));
  const MayaSelectionMenuContext context = selection_menu_context_get(C);
  if (!selection_command_enabled(context, command)) {
    return OPERATOR_CANCELLED;
  }

  const wmOperatorStatus status = selection_command_execute(C, command);
  if (!(status & OPERATOR_FINISHED)) {
    return OPERATOR_CANCELLED;
  }

  /* A conversion changes the component type, and the Maya runtime has to hear about it or the
   * next mode query answers with the type the selection no longer has. */
  const MayaComponentMode result_mode = command_result_component_mode(command);
  if (result_mode != MayaComponentMode::Object) {
    if (MayaWindowRuntime *runtime = runtime_ensure(C)) {
      runtime->component_mode = result_mode;
      runtime->last_component_mode = result_mode;
    }
  }
  return OPERATOR_FINISHED;
}

static void MAYA_OT_selection_command(wmOperatorType *ot)
{
  ot->name = "Maya Selection Command";
  ot->description = "Convert, grow or shrink the polygon component selection the Maya way";
  ot->idname = "MAYA_OT_selection_command";
  ot->exec = maya_selection_command_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_enum(ot->srna,
               "command",
               maya_selection_command_items,
               int(MayaSelectionCommand::ToVertices),
               "Command",
               "");
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Menus
 * \{ */

static bool selection_menu_poll(const bContext *C, MenuType * /*mt*/)
{
  const ARegion *region = CTX_wm_region(C);
  if (CTX_wm_view3d(C) == nullptr || region == nullptr || region->regiontype != RGN_TYPE_WINDOW) {
    return false;
  }
  /* Maya only offers this menu once there are components to convert. */
  return selection_menu_context_get(C).has_selection;
}

static const char *command_label(const MayaSelectionCommand command)
{
  for (const EnumPropertyItem *item = maya_selection_command_items; item->identifier != nullptr;
       item++)
  {
    if (item->value == int(command)) {
      return item->name;
    }
  }
  return "";
}

static void command_item(ui::Layout &layout,
                         const MayaSelectionMenuContext &context,
                         const MayaSelectionCommand command)
{
  ui::Layout &row = layout.row(false);
  row.enabled_set(selection_command_enabled(context, command));
  PointerRNA op_ptr = row.op("MAYA_OT_selection_command",
                             command_label(command),
                             ICON_NONE,
                             wm::OpCallContext::ExecDefault,
                             UI_ITEM_NONE);
  RNA_enum_set(&op_ptr, "command", int(command));
}

/** One submenu draw for every group, so the marking menu can be read as one table. */
struct SelectionSubmenu {
  const char *idname;
  const char *label;
  MayaSelectionCommand commands[4];
  int commands_num;
};

static const SelectionSubmenu selection_submenus[] = {
    {"VIEW3D_MT_maya_select_to_edges",
     "To Edges",
     {MayaSelectionCommand::ToEdges,
      MayaSelectionCommand::ToContainedEdges,
      MayaSelectionCommand::ToEdgePerimeter},
     3},
    {"VIEW3D_MT_maya_select_to_vertices",
     "To Vertices",
     {MayaSelectionCommand::ToVertices, MayaSelectionCommand::ToVertexPerimeter},
     2},
    {"VIEW3D_MT_maya_select_to_faces",
     "To Faces",
     {MayaSelectionCommand::ToFaces,
      MayaSelectionCommand::ToContainedFaces,
      MayaSelectionCommand::ToFacePerimeter},
     3},
    {"VIEW3D_MT_maya_select_to_uvs",
     "To UVs",
     {MayaSelectionCommand::ToUVs,
      MayaSelectionCommand::ToUVPerimeter,
      MayaSelectionCommand::ToUVEdgeLoop},
     3},
    {"VIEW3D_MT_maya_select_grow",
     "Grow Selection",
     {MayaSelectionCommand::Grow, MayaSelectionCommand::GrowAlongLoop},
     2},
    {"VIEW3D_MT_maya_select_shrink",
     "Shrink Selection",
     {MayaSelectionCommand::Shrink, MayaSelectionCommand::ShrinkAlongLoop},
     2},
    {"VIEW3D_MT_maya_select_edge_ring",
     "Edge Ring Utilities",
     {MayaSelectionCommand::ToEdgeRing,
      MayaSelectionCommand::SelectEdgeRingTool,
      MayaSelectionCommand::ToEdgeRingAndSplit,
      MayaSelectionCommand::ToEdgeRingAndCollapse},
     4},
    {"VIEW3D_MT_maya_select_edge_loop",
     "Edge Loop Utilities",
     {MayaSelectionCommand::ToEdgeLoop,
      MayaSelectionCommand::SelectEdgeLoopTool,
      MayaSelectionCommand::ToEdgeLoopAndDuplicate,
      MayaSelectionCommand::ToEdgeLoopAndDelete},
     4},
};

static void selection_submenu_draw(const bContext *C, Menu *menu)
{
  const MayaSelectionMenuContext context = selection_menu_context_get(C);
  for (const SelectionSubmenu &submenu : selection_submenus) {
    if (!STREQ(submenu.idname, menu->type->idname)) {
      continue;
    }
    for (int i = 0; i < submenu.commands_num; i++) {
      command_item(*menu->layout, context, submenu.commands[i]);
    }
    return;
  }
}

static void maya_selection_marking_menu_draw(const bContext *C, Menu *menu)
{
  const MayaSelectionMenuContext context = selection_menu_context_get(C);

  /* Radial slots are filled in the order W, E, S, N, NW, NE, SW, SE. */
  ui::Layout &pie = menu->layout->menu_pie();
  pie.menu(selection_submenus[0].idname, selection_submenus[0].label, ICON_NONE); /* To Edges */
  pie.menu(selection_submenus[2].idname, selection_submenus[2].label, ICON_NONE); /* To Faces */
  pie.menu(selection_submenus[3].idname, selection_submenus[3].label, ICON_NONE); /* To UVs */
  pie.menu(selection_submenus[1].idname, selection_submenus[1].label, ICON_NONE); /* To Vertices */
  pie.menu(selection_submenus[4].idname, selection_submenus[4].label, ICON_NONE); /* Grow */
  pie.menu(selection_submenus[5].idname, selection_submenus[5].label, ICON_NONE); /* Shrink */
  pie.menu(selection_submenus[7].idname, selection_submenus[7].label, ICON_NONE); /* Edge Loop */
  pie.menu(selection_submenus[6].idname, selection_submenus[6].label, ICON_NONE); /* Edge Ring */

  ui::Layout &list = menu->layout->column(false);
  command_item(list, context, MayaSelectionCommand::ToFacePath);
  command_item(list, context, MayaSelectionCommand::ToUVShell);
  command_item(list, context, MayaSelectionCommand::ToShell);
  command_item(list, context, MayaSelectionCommand::ToShellBorder);
  command_item(list, context, MayaSelectionCommand::SelectBorderEdgeTool);
  command_item(list, context, MayaSelectionCommand::SelectionBoundary);
  list.separator();
  /* The same global `polySelectConstraint` state the Move Tool marking menu shows. */
  list.menu("VIEW3D_MT_maya_selection_constraints", "Selection Constraints", ICON_NONE);
}

static void selection_menutype_register(const char *idname,
                              void (*draw)(const bContext *, Menu *),
                              bool (*poll)(const bContext *, MenuType *))
{
  MenuType *type = MEM_new<MenuType>(__func__);
  STRNCPY_UTF8(type->idname, idname);
  type->draw = draw;
  type->poll = poll;
  WM_menutype_add(type);
}

void register_selection_menu_types()
{
  WM_operatortype_append(MAYA_OT_selection_command);

  selection_menutype_register(
      "VIEW3D_MT_maya_selection_marking_menu", maya_selection_marking_menu_draw, selection_menu_poll);
  for (const SelectionSubmenu &submenu : selection_submenus) {
    selection_menutype_register(submenu.idname, selection_submenu_draw, nullptr);
  }
}

/** \} */

}  // namespace ed::maya
}  // namespace blender
