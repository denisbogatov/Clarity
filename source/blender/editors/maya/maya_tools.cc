/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_tools.hh"

#include <array>
#include <cstdint>
#include <memory>

#include "DNA_layer_types.h"
#include "DNA_mesh_types.h"
#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_view3d_types.h"
#include "DNA_windowmanager_types.h"

#include "BLI_listbase_iterator.hh"
#include "BLI_map.hh"
#include "BLI_index_range.hh"
#include "BLI_math_matrix.h"
#include "BLI_math_vector.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"
#include "BKE_editmesh.hh"
#include "BKE_layer.hh"
#include "BKE_lib_id.hh"
#include "BKE_object.hh"
#include "BKE_object_transform_maya.hh"
#include "BKE_report.hh"

#include "DEG_depsgraph.hh"
#include "DEG_depsgraph_build.hh"

#include "ED_maya.hh"
#include "ED_mesh.hh"
#include "ED_object.hh"
#include "ED_screen.hh"
#include "ED_select_utils.hh"
#include "ED_undo.hh"
#include "ED_view3d.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"
#include "wm_event_types.hh"

#include "bmesh.hh"

#include "maya_input.hh"
#include "maya_runtime.hh"

namespace blender::ed::maya {

struct MayaStoredSelectionHistoryEntry {
  uintptr_t element = 0;
  char htype = 0;
};

struct MayaStoredComponentSelection {
  Vector<uintptr_t> elements;
  Vector<MayaStoredSelectionHistoryEntry> history;
};

struct MayaStoredMeshSelection {
  uint64_t topology_fingerprint = 0;
  std::array<MayaStoredComponentSelection, 3> domains;
  uintptr_t active_face = 0;
};

struct MayaSelectionMemory {
  Map<uint32_t, MayaStoredMeshSelection> meshes;
};

struct MayaEditMeshBackup {
  Object *object = nullptr;
  BMBackup backup{};
};

struct MayaShiftTransformState {
  enum class Kind : uint8_t {
    ObjectDuplicate,
    ComponentExtrude,
  };

  Kind kind = Kind::ObjectDuplicate;
  Scene *scene = nullptr;
  ViewLayer *view_layer = nullptr;
  Object *active_source = nullptr;
  Vector<Object *> source_objects;
  Vector<Object *> result_objects;
  Vector<ID *> result_data;
  Vector<MayaEditMeshBackup> edit_mesh_backups;

  ~MayaShiftTransformState()
  {
    for (MayaEditMeshBackup &item : edit_mesh_backups) {
      EDBM_redo_state_free(&item.backup);
    }
  }
};

static int component_mode_select_bits(const MayaComponentMode mode)
{
  switch (mode) {
    case MayaComponentMode::Vertex:
    case MayaComponentMode::UV:
      return SCE_SELECT_VERTEX;
    case MayaComponentMode::Edge:
      return SCE_SELECT_EDGE;
    case MayaComponentMode::Face:
      return SCE_SELECT_FACE;
    case MayaComponentMode::VertexFace:
      return SCE_SELECT_VERTEX | SCE_SELECT_FACE;
    case MayaComponentMode::Multi:
      return SCE_SELECT_VERTEX | SCE_SELECT_EDGE | SCE_SELECT_FACE;
    case MayaComponentMode::Object:
      return 0;
  }
  BLI_assert_unreachable();
  return 0;
}

static uint64_t topology_hash_combine(uint64_t hash, const uintptr_t value)
{
  hash ^= uint64_t(value) + 0x9e3779b97f4a7c15ULL + (hash << 6) + (hash >> 2);
  return hash;
}

static uint64_t component_topology_fingerprint(const BMesh &bm)
{
  uint64_t hash = topology_hash_combine(0xcbf29ce484222325ULL,
                                        reinterpret_cast<uintptr_t>(&bm));
  hash = topology_hash_combine(hash, uintptr_t(bm.totvert));
  hash = topology_hash_combine(hash, uintptr_t(bm.totedge));
  hash = topology_hash_combine(hash, uintptr_t(bm.totface));

  BMIter iter;
  BMVert *vert;
  BM_ITER_MESH (vert, &iter, const_cast<BMesh *>(&bm), BM_VERTS_OF_MESH) {
    hash = topology_hash_combine(hash, reinterpret_cast<uintptr_t>(vert));
  }

  BMEdge *edge;
  BM_ITER_MESH (edge, &iter, const_cast<BMesh *>(&bm), BM_EDGES_OF_MESH) {
    hash = topology_hash_combine(hash, reinterpret_cast<uintptr_t>(edge));
    hash = topology_hash_combine(hash, reinterpret_cast<uintptr_t>(edge->v1));
    hash = topology_hash_combine(hash, reinterpret_cast<uintptr_t>(edge->v2));
  }

  BMFace *face;
  BM_ITER_MESH (face, &iter, const_cast<BMesh *>(&bm), BM_FACES_OF_MESH) {
    hash = topology_hash_combine(hash, reinterpret_cast<uintptr_t>(face));
    hash = topology_hash_combine(hash, uintptr_t(face->len));
    BMLoop *loop = face->l_first;
    for (int i = 0; i < face->len; i++, loop = loop->next) {
      hash = topology_hash_combine(hash, reinterpret_cast<uintptr_t>(loop));
      hash = topology_hash_combine(hash, reinterpret_cast<uintptr_t>(loop->v));
      hash = topology_hash_combine(hash, reinterpret_cast<uintptr_t>(loop->e));
    }
  }
  return hash;
}

static uint32_t component_mesh_uid_ensure(Mesh &mesh)
{
  BKE_lib_libblock_session_uid_ensure(&mesh.id);
  return mesh.id.session_uid;
}

static void component_selection_memory_prune(Main &bmain, MayaSelectionMemory &memory)
{
  memory.meshes.remove_if([&](const auto item) {
    return BKE_libblock_find_session_uid(&bmain, ID_ME, item.key) == nullptr;
  });
}

static void component_selection_store(MayaSelectionMemory &memory,
                                      Main &bmain,
                                      Object *object,
                                      const int select_bits)
{
  BMEditMesh *em = BKE_editmesh_from_object(object);
  if (em == nullptr || em->bm == nullptr) {
    return;
  }

  BMesh *bm = em->bm;
  Mesh *mesh = id_cast<Mesh *>(object->data);
  component_selection_memory_prune(bmain, memory);
  MayaStoredMeshSelection &stored = memory.meshes.lookup_or_add_default(
      component_mesh_uid_ensure(*mesh));
  const uint64_t fingerprint = component_topology_fingerprint(*bm);
  if (stored.topology_fingerprint != fingerprint) {
    stored = {};
    stored.topology_fingerprint = fingerprint;
  }

  const char htypes[3] = {BM_VERT, BM_EDGE, BM_FACE};
  const char iter_types[3] = {BM_VERTS_OF_MESH, BM_EDGES_OF_MESH, BM_FACES_OF_MESH};
  const int select_types[3] = {SCE_SELECT_VERTEX, SCE_SELECT_EDGE, SCE_SELECT_FACE};
  for (const int domain : IndexRange(3)) {
    if ((select_bits & select_types[domain]) == 0) {
      continue;
    }

    MayaStoredComponentSelection &selection = stored.domains[domain];
    selection.elements.clear();
    selection.history.clear();

    BMIter iter;
    BMElem *element;
    BM_ITER_MESH (element, &iter, bm, iter_types[domain]) {
      if (BM_elem_flag_test(element, BM_ELEM_SELECT)) {
        selection.elements.append(reinterpret_cast<uintptr_t>(element));
      }
    }
    for (const BMEditSelection &item : bm->selected) {
      if (item.htype == htypes[domain] && BM_elem_flag_test(item.ele, BM_ELEM_SELECT)) {
        selection.history.append({reinterpret_cast<uintptr_t>(item.ele), item.htype});
      }
    }
  }
  if (select_bits & SCE_SELECT_FACE) {
    stored.active_face = (bm->act_face != nullptr &&
                          BM_elem_flag_test(bm->act_face, BM_ELEM_SELECT)) ?
                             reinterpret_cast<uintptr_t>(bm->act_face) :
                             0;
  }
}

static void component_selection_restore(MayaSelectionMemory &memory,
                                        Main &bmain,
                                        Object *object,
                                        const int select_bits)
{
  BMEditMesh *em = BKE_editmesh_from_object(object);
  if (em == nullptr || em->bm == nullptr) {
    return;
  }

  BMesh *bm = em->bm;
  Mesh *mesh = id_cast<Mesh *>(object->data);
  component_selection_memory_prune(bmain, memory);
  const uint32_t mesh_uid = component_mesh_uid_ensure(*mesh);
  MayaStoredMeshSelection *stored = memory.meshes.lookup_ptr(mesh_uid);
  if (stored != nullptr &&
      stored->topology_fingerprint != component_topology_fingerprint(*bm))
  {
    memory.meshes.remove(mesh_uid);
    stored = nullptr;
  }

  em->selectmode = short(select_bits);
  bm->selectmode = short(select_bits);
  BM_mesh_elem_hflag_disable_all(
      bm, BM_VERT | BM_EDGE | BM_FACE, BM_ELEM_SELECT, false);
  BM_select_history_clear(bm);

  const int select_types[3] = {SCE_SELECT_VERTEX, SCE_SELECT_EDGE, SCE_SELECT_FACE};
  for (const int domain : IndexRange(3)) {
    if ((select_bits & select_types[domain]) == 0 || stored == nullptr) {
      continue;
    }

    for (const uintptr_t address : stored->domains[domain].elements) {
      BMElem *element = reinterpret_cast<BMElem *>(address);
      if (domain == 0) {
        BM_vert_select_set(bm, reinterpret_cast<BMVert *>(element), true);
      }
      else if (domain == 1) {
        BM_edge_select_set(bm, reinterpret_cast<BMEdge *>(element), true);
      }
      else {
        BM_face_select_set(bm, reinterpret_cast<BMFace *>(element), true);
      }
    }
  }

  if (stored != nullptr) {
    for (const int domain : IndexRange(3)) {
      if ((select_bits & select_types[domain]) == 0) {
        continue;
      }
      for (const MayaStoredSelectionHistoryEntry &item : stored->domains[domain].history) {
        BMElem *element = reinterpret_cast<BMElem *>(item.element);
        if (BM_elem_flag_test(element, BM_ELEM_SELECT)) {
          BM_select_history_store(bm, element);
        }
      }
    }
    if (stored->active_face != 0) {
      BMFace *active_face = reinterpret_cast<BMFace *>(stored->active_face);
      if (BM_elem_flag_test(active_face, BM_ELEM_SELECT)) {
        BM_mesh_active_face_set(bm, active_face);
      }
    }
  }

  EDBMUpdate_Params params{};
  params.calc_looptris = false;
  params.calc_normals = false;
  params.is_destructive = false;
  EDBM_update(id_cast<Mesh *>(object->data), &params);
}

static Vector<Object *> edit_mesh_objects_get(const bContext *C)
{
  const Main *bmain = CTX_data_main(C);
  const Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);
  const View3D *v3d = CTX_wm_view3d(C);
  return BKE_view_layer_array_from_objects_in_edit_mode_unique_data(
      *bmain, scene, view_layer, v3d);
}

static MayaComponentMode component_mode_from_context(const bContext *C,
                                                     const MayaWindowRuntime &runtime)
{
  const Object *object = CTX_data_edit_object(C);
  if (object == nullptr || object->type != OB_MESH) {
    return MayaComponentMode::Object;
  }
  const Scene *scene = CTX_data_scene(C);
  const int select_mode = scene->toolsettings->selectmode;
  if (runtime.component_mode != MayaComponentMode::Object &&
      component_mode_select_bits(runtime.component_mode) == select_mode)
  {
    return runtime.component_mode;
  }
  if (select_mode == (SCE_SELECT_VERTEX | SCE_SELECT_EDGE | SCE_SELECT_FACE)) {
    return MayaComponentMode::Multi;
  }
  if (select_mode == (SCE_SELECT_VERTEX | SCE_SELECT_FACE)) {
    return MayaComponentMode::VertexFace;
  }
  if (select_mode & SCE_SELECT_FACE) {
    return MayaComponentMode::Face;
  }
  if (select_mode & SCE_SELECT_EDGE) {
    return MayaComponentMode::Edge;
  }
  return MayaComponentMode::Vertex;
}

static bool component_mode_set(bContext *C,
                               MayaWindowRuntime &runtime,
                               const MayaComponentMode requested_mode)
{
  MayaComponentMode current_mode = component_mode_from_context(C, runtime);
  const MayaComponentMode target_mode = requested_mode;
  if (current_mode == target_mode) {
    runtime.component_mode = target_mode;
    if (target_mode != MayaComponentMode::Object) {
      runtime.last_component_mode = target_mode;
    }
    return true;
  }

  if (!runtime.selection_memory) {
    runtime.selection_memory = std::make_shared<MayaSelectionMemory>();
  }

  if (current_mode != MayaComponentMode::Object &&
      runtime.selection_settings.preserve_component_selection)
  {
    const int current_bits = component_mode_select_bits(current_mode);
    Main *bmain = CTX_data_main(C);
    for (Object *object : edit_mesh_objects_get(C)) {
      component_selection_store(*runtime.selection_memory, *bmain, object, current_bits);
    }
  }

  if (target_mode == MayaComponentMode::Object) {
    const wmOperatorStatus status = WM_operator_name_call(
        C, "OBJECT_OT_editmode_toggle", wm::OpCallContext::ExecDefault, nullptr, nullptr);
    if (!(status & OPERATOR_FINISHED)) {
      return false;
    }
    runtime.component_mode = MayaComponentMode::Object;
    return true;
  }

  if (current_mode == MayaComponentMode::Object) {
    const Object *active = CTX_data_active_object(C);
    if (active == nullptr || active->type != OB_MESH || active->mode != OB_MODE_OBJECT) {
      return false;
    }
    const wmOperatorStatus status = WM_operator_name_call(
        C, "OBJECT_OT_editmode_toggle", wm::OpCallContext::ExecDefault, nullptr, nullptr);
    if (!(status & OPERATOR_FINISHED)) {
      return false;
    }
  }

  Object *edit_object = CTX_data_edit_object(C);
  if (edit_object == nullptr || edit_object->type != OB_MESH) {
    return false;
  }

  const int target_bits = component_mode_select_bits(target_mode);
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  scene->toolsettings->selectmode = short(target_bits);
  for (Object *object : edit_mesh_objects_get(C)) {
    if (runtime.selection_settings.preserve_component_selection) {
      component_selection_restore(*runtime.selection_memory, *bmain, object, target_bits);
    }
    else {
      BMEditMesh *em = BKE_editmesh_from_object(object);
      EDBM_selectmode_set(em, short(target_bits));
    }
  }

  runtime.component_mode = target_mode;
  runtime.last_component_mode = target_mode;
  WM_event_add_notifier(C, NC_SCENE | ND_TOOLSETTINGS, scene);
  WM_event_add_notifier(C, NC_GEOM | ND_SELECT, edit_object->data);
  return true;
}

static const EnumPropertyItem maya_component_mode_items[] = {
    {int(MayaComponentMode::Object), "OBJECT", 0, "Object", "Select whole objects"},
    {int(MayaComponentMode::Vertex), "VERTEX", 0, "Vertex", "Select mesh vertices"},
    {int(MayaComponentMode::Edge), "EDGE", 0, "Edge", "Select mesh edges"},
    {int(MayaComponentMode::Face), "FACE", 0, "Face", "Select mesh faces"},
    {int(MayaComponentMode::UV),
     "UV",
     0,
     "UV (Experimental)",
     "Experimental compatibility mode; currently uses mesh vertices, not per-corner UVs"},
    {int(MayaComponentMode::VertexFace),
     "VERTEX_FACE",
     0,
     "Vertex Face (Experimental)",
     "Experimental compatibility mode; currently combines vertex and face selection"},
    {int(MayaComponentMode::Multi),
     "MULTI",
     0,
     "Multi-Component",
     "Select vertices, edges, and faces together"},
    {0, nullptr, 0, nullptr, nullptr},
};

static const EnumPropertyItem maya_camera_based_selection_items[] = {
    {int(MayaCameraBasedSelection::Off),
     "OFF",
     0,
     "Off",
     "Select through the mesh without camera-depth filtering"},
    {int(MayaCameraBasedSelection::On),
     "ON",
     0,
     "On",
     "Use camera-depth filtering when the viewport supports it"},
    {int(MayaCameraBasedSelection::Auto),
     "AUTO",
     0,
     "Auto",
     "Use camera-depth filtering in shaded non-X-Ray views"},
    {0, nullptr, 0, nullptr, nullptr},
};

static wmOperatorStatus maya_component_mode_set_exec(bContext *C, wmOperator *op)
{
  MayaWindowRuntime *runtime = runtime_ensure(C);
  if (runtime == nullptr) {
    return OPERATOR_CANCELLED;
  }
  const MayaComponentMode mode = MayaComponentMode(RNA_enum_get(op->ptr, "mode"));
  return component_mode_set(C, *runtime, mode) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static void MAYA_OT_component_mode_set(wmOperatorType *ot)
{
  ot->name = "Maya Component Mode";
  ot->description = "Switch object or polygon component mode while preserving each component set";
  ot->idname = "MAYA_OT_component_mode_set";
  ot->exec = maya_component_mode_set_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_UNDO;
  RNA_def_enum(ot->srna,
               "mode",
               maya_component_mode_items,
               int(MayaComponentMode::Vertex),
               "Mode",
               "");
}

static wmOperatorStatus maya_selection_settings_set_exec(bContext *C, wmOperator *op)
{
  MayaWindowRuntime *runtime = runtime_ensure(C);
  if (runtime == nullptr) {
    return OPERATOR_CANCELLED;
  }
  MayaSelectionSettings &settings = runtime->selection_settings;
  if (RNA_struct_property_is_set(op->ptr, "click_box_size")) {
    settings.click_box_size = RNA_float_get(op->ptr, "click_box_size");
  }
  if (RNA_struct_property_is_set(op->ptr, "manipulation_box_size")) {
    settings.manipulation_box_size = RNA_float_get(op->ptr, "manipulation_box_size");
  }
  if (RNA_struct_property_is_set(op->ptr, "camera_based_selection")) {
    settings.camera_based_selection = MayaCameraBasedSelection(
        RNA_enum_get(op->ptr, "camera_based_selection"));
  }
  if (RNA_struct_property_is_set(op->ptr, "highlight_backfaces")) {
    settings.highlight_backfaces = RNA_boolean_get(op->ptr, "highlight_backfaces");
  }
  return OPERATOR_FINISHED;
}

static void MAYA_OT_selection_settings_set(wmOperatorType *ot)
{
  ot->name = "Maya Selection Settings";
  ot->description = "Set per-window Maya selection behavior";
  ot->idname = "MAYA_OT_selection_settings_set";
  ot->exec = maya_selection_settings_set_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER;

  RNA_def_float(ot->srna,
                "click_box_size",
                4.0f,
                0.0f,
                100.0f,
                "Click Box Size",
                "Maya selection hit radius in pixels",
                0.0f,
                20.0f);
  RNA_def_float(ot->srna,
                "manipulation_box_size",
                10.0f,
                0.0f,
                100.0f,
                "Manipulation Box Size",
                "Independent interaction radius reserved for manipulators",
                0.0f,
                30.0f);
  RNA_def_enum(ot->srna,
               "camera_based_selection",
               maya_camera_based_selection_items,
               int(MayaCameraBasedSelection::Off),
               "Camera Based Selection",
               "");
  RNA_def_boolean(ot->srna,
                  "highlight_backfaces",
                  true,
                  "Highlight Backfaces",
                  "Keep backface highlighting independent from camera-based selection");
}

static wmOperatorStatus maya_pivot_pin_toggle_exec(bContext *C, wmOperator * /*op*/)
{
  MayaWindowRuntime *runtime = runtime_ensure(C);
  if (runtime == nullptr || !pivot_edit_pin_toggle(C, *runtime)) {
    return OPERATOR_CANCELLED;
  }
  return OPERATOR_FINISHED;
}

static void MAYA_OT_pivot_pin_toggle(wmOperatorType *ot)
{
  ot->name = "Maya Pin Pivot";
  ot->description = "Keep the custom component pivot when the component selection changes";
  ot->idname = "MAYA_OT_pivot_pin_toggle";
  ot->exec = maya_pivot_pin_toggle_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
}

static const EnumPropertyItem maya_pivot_reset_mode_items[] = {
    {MAYA_PIVOT_RESET_CENTER,
     "CENTER",
     0,
     "Center",
     "Reset the pivot position to the object hierarchy or component bounding-box center"},
    {MAYA_PIVOT_RESET_ZERO,
     "ZERO",
     0,
     "Zero",
     "Reset the object pivot channels to zero or use the component object's origin"},
    {0, nullptr, 0, nullptr, nullptr},
};

static const EnumPropertyItem maya_pivot_reset_action_items[] = {
    {0, "POSITION", 0, "Position", "Reset only the pivot position"},
    {1, "ORIENTATION", 0, "Orientation", "Reset only the manipulator orientation"},
    {2, "BOTH", 0, "Both", "Reset pivot position and orientation"},
    {0, nullptr, 0, nullptr, nullptr},
};

static const EnumPropertyItem maya_pivot_bake_mode_items[] = {
    {MAYA_PIVOT_BAKE_POSITION, "POSITION", 0, "Position", "Bake the custom pivot position"},
    {MAYA_PIVOT_BAKE_ORIENTATION,
     "ORIENTATION",
     0,
     "Orientation",
     "Bake the custom pivot orientation"},
    {MAYA_PIVOT_BAKE_BOTH, "BOTH", 0, "Both", "Bake custom position and orientation"},
    {0, nullptr, 0, nullptr, nullptr},
};

static wmOperatorStatus maya_pivot_edit_toggle_exec(bContext *C, wmOperator * /*op*/)
{
  MayaWindowRuntime *runtime = runtime_ensure(C);
  return runtime != nullptr && pivot_edit_toggle_persistent(C, *runtime) ? OPERATOR_FINISHED :
                                                                          OPERATOR_CANCELLED;
}

static void MAYA_OT_pivot_edit_toggle(wmOperatorType *ot)
{
  ot->name = "Maya Edit Pivot";
  ot->description = "Enter or leave persistent Maya Edit Pivot mode";
  ot->idname = "MAYA_OT_pivot_edit_toggle";
  ot->exec = maya_pivot_edit_toggle_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER;
}

static wmOperatorStatus maya_pivot_settings_set_exec(bContext *C, wmOperator *op)
{
  MayaPivotToolSettings settings;
  ED_maya_pivot_tool_settings_get(C, settings);
  if (RNA_struct_property_is_set(op->ptr, "snap_position")) {
    settings.snap_position = RNA_boolean_get(op->ptr, "snap_position");
  }
  if (RNA_struct_property_is_set(op->ptr, "snap_orientation")) {
    settings.snap_orientation = RNA_boolean_get(op->ptr, "snap_orientation");
  }
  if (RNA_struct_property_is_set(op->ptr, "bake_orientation_automatically")) {
    settings.bake_orientation_automatically = RNA_boolean_get(
        op->ptr, "bake_orientation_automatically");
  }
  if (RNA_struct_property_is_set(op->ptr, "preserve_children")) {
    settings.preserve_children = RNA_boolean_get(op->ptr, "preserve_children");
  }
  if (RNA_struct_property_is_set(op->ptr, "show_orientation_handle")) {
    settings.show_orientation_handle = RNA_boolean_get(op->ptr, "show_orientation_handle");
  }
  if (RNA_struct_property_is_set(op->ptr, "reset_mode")) {
    settings.reset_mode = eMayaPivotResetMode(RNA_enum_get(op->ptr, "reset_mode"));
  }
  return ED_maya_pivot_tool_settings_set(C, settings) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static void MAYA_OT_pivot_settings_set(wmOperatorType *ot)
{
  ot->name = "Maya Pivot Settings";
  ot->description = "Set Maya manipulator-pivot behavior";
  ot->idname = "MAYA_OT_pivot_settings_set";
  ot->exec = maya_pivot_settings_set_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER;
  RNA_def_boolean(
      ot->srna, "snap_position", true, "Snap Position", "Apply snap targets to pivot position");
  RNA_def_boolean(ot->srna,
                  "snap_orientation",
                  true,
                  "Snap Orientation",
                  "Apply available target orientation independently from position");
  RNA_def_boolean(ot->srna,
                  "bake_orientation_automatically",
                  false,
                  "Bake Pivot Orientation",
                  "Bake the custom orientation when an orientation edit is committed");
  RNA_def_boolean(ot->srna,
                  "preserve_children",
                  true,
                  "Preserve Child Position",
                  "Keep direct children in world space while baking the pivot");
  RNA_def_boolean(ot->srna,
                  "show_orientation_handle",
                  true,
                  "Show Orientation Handle",
                  "Show rotation handles while Edit Pivot is active");
  RNA_def_enum(ot->srna,
               "reset_mode",
               maya_pivot_reset_mode_items,
               MAYA_PIVOT_RESET_CENTER,
               "Reset Mode",
               "");
}

static wmOperatorStatus maya_pivot_reset_exec(bContext *C, wmOperator *op)
{
  ED_maya_pivot_undo_begin(C);
  MayaPivotToolSettings settings;
  ED_maya_pivot_tool_settings_get(C, settings);
  const eMayaPivotResetMode mode = RNA_struct_property_is_set(op->ptr, "mode") ?
                                       eMayaPivotResetMode(RNA_enum_get(op->ptr, "mode")) :
                                       settings.reset_mode;
  switch (RNA_enum_get(op->ptr, "action")) {
    case 0:
      ED_maya_pivot_reset_position(C, mode);
      break;
    case 1:
      ED_maya_pivot_reset_orientation(C);
      break;
    case 2:
      ED_maya_pivot_reset_all(C, mode);
      break;
    default:
      return OPERATOR_CANCELLED;
  }
  return OPERATOR_FINISHED;
}

static void MAYA_OT_pivot_reset(wmOperatorType *ot)
{
  ot->name = "Reset Maya Pivot";
  ot->description = "Reset Maya pivot position, orientation, or both";
  ot->idname = "MAYA_OT_pivot_reset";
  ot->exec = maya_pivot_reset_exec;
  ot->poll = ED_operator_view3d_active;
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
  RNA_def_enum(ot->srna, "action", maya_pivot_reset_action_items, 2, "Reset", "");
  RNA_def_enum(
      ot->srna, "mode", maya_pivot_reset_mode_items, MAYA_PIVOT_RESET_CENTER, "Mode", "");
}

static wmOperatorStatus maya_pivot_bake_exec(bContext *C, wmOperator *op)
{
  ED_maya_pivot_undo_begin(C);
  if (!ED_maya_pivot_bake(C, eMayaPivotBakeMode(RNA_enum_get(op->ptr, "mode")))) {
    ED_maya_undo_step_clear(C);
    BKE_report(op->reports,
               RPT_WARNING,
               "Bake Pivot requires valid custom pivot data, no constraints, a supported object "
               "type, and single-user geometry when data compensation is needed");
    return OPERATOR_CANCELLED;
  }
  return OPERATOR_FINISHED;
}

static bool maya_pivot_bake_poll(bContext *C)
{
  if (!ED_operator_objectmode(C)) {
    return false;
  }
  const Main *bmain = CTX_data_main(C);
  const Object *object = CTX_data_active_object(C);
  if (bmain == nullptr || object == nullptr || !BKE_id_is_editable(bmain, &object->id) ||
      object->constraints.first != nullptr || object->maya_constraints.first != nullptr)
  {
    return false;
  }
  const MayaTransformCapabilities capabilities = BKE_maya_transform_capabilities_get(*object);
  return capabilities.bake_position || capabilities.bake_orientation;
}

static void MAYA_OT_pivot_bake(wmOperatorType *ot)
{
  ot->name = "Bake Maya Pivot";
  ot->description = "Bake Maya manipulator pivot state into the object and its geometry";
  ot->idname = "MAYA_OT_pivot_bake";
  ot->exec = maya_pivot_bake_exec;
  ot->poll = maya_pivot_bake_poll;
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
  RNA_def_enum(ot->srna,
               "mode",
               maya_pivot_bake_mode_items,
               MAYA_PIVOT_BAKE_BOTH,
               "Bake",
               "");
}

void register_tool_operators()
{
  WM_operatortype_append(MAYA_OT_component_mode_set);
  WM_operatortype_append(MAYA_OT_selection_settings_set);
  WM_operatortype_append(MAYA_OT_pivot_pin_toggle);
  WM_operatortype_append(MAYA_OT_pivot_edit_toggle);
  WM_operatortype_append(MAYA_OT_pivot_settings_set);
  WM_operatortype_append(MAYA_OT_pivot_reset);
  WM_operatortype_append(MAYA_OT_pivot_bake);
}

static wmOperatorStatus component_mode_operator_call(bContext *C, const MayaComponentMode mode)
{
  wmOperatorType *ot = WM_operatortype_find("MAYA_OT_component_mode_set", true);
  PointerRNA ptr = WM_operator_properties_create_ptr(ot);
  RNA_enum_set(&ptr, "mode", int(mode));
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::ExecDefault, &ptr, nullptr);
  WM_operator_properties_free(&ptr);
  return status;
}

static wmOperatorStatus select_pick_call(bContext *C,
                                         const MayaInputAction &action,
                                         const eSelectOp select_op)
{
  wmOperatorType *ot = WM_operatortype_find("VIEW3D_OT_select", true);
  PointerRNA ptr = WM_operator_properties_create_ptr(ot);
  RNA_boolean_set(&ptr, "extend", select_op == SEL_OP_ADD);
  RNA_boolean_set(&ptr, "deselect", select_op == SEL_OP_SUB);
  RNA_boolean_set(&ptr, "toggle", select_op == SEL_OP_XOR);
  RNA_boolean_set(&ptr, "deselect_all", select_op == SEL_OP_SET);
  MayaWindowRuntime *runtime = runtime_ensure(C);
  if (runtime != nullptr) {
    RNA_float_set(&ptr, "select_radius", runtime->selection_settings.click_box_size);
  }
  const int location[2] = {action.mouse_region.x, action.mouse_region.y};
  RNA_int_set_array(&ptr, "location", location);
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::ExecDefault, &ptr, nullptr);
  WM_operator_properties_free(&ptr);
  return status;
}

static wmOperatorStatus select_marquee_call(bContext *C, const MayaInputAction &action)
{
  eSelectOp select_op = SEL_OP_SET;
  if (action.ctrl && action.shift) {
    select_op = SEL_OP_ADD;
  }
  else if (action.ctrl) {
    select_op = SEL_OP_SUB;
  }
  else if (action.shift) {
    select_op = SEL_OP_XOR;
  }

  wmOperatorType *ot = WM_operatortype_find("VIEW3D_OT_select_box", true);
  PointerRNA ptr = WM_operator_properties_create_ptr(ot);
  RNA_enum_set(&ptr, "mode", select_op);
  bool use_depth = false;
  const MayaWindowRuntime *runtime = runtime_get(C);
  if (runtime != nullptr) {
    switch (runtime->selection_settings.camera_based_selection) {
      case MayaCameraBasedSelection::Off:
        use_depth = false;
        break;
      case MayaCameraBasedSelection::On:
        use_depth = true;
        break;
      case MayaCameraBasedSelection::Auto: {
        const View3D *v3d = CTX_wm_view3d(C);
        use_depth = v3d != nullptr && v3d->shading.type > OB_WIRE &&
                    !XRAY_FLAG_ENABLED(v3d);
        break;
      }
    }
  }
  RNA_boolean_set(&ptr, "use_depth", use_depth);
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::InvokeDefault, &ptr, action.source_event);
  WM_operator_properties_free(&ptr);
  return status;
}

static bool is_mesh_component_context(const bContext *C)
{
  const Object *object = CTX_data_edit_object(C);
  return object != nullptr && object->type == OB_MESH;
}

struct MayaEdgePathPick {
  BMEditMesh *edit_mesh = nullptr;
  BMEdge *source = nullptr;
  BMEdge *destination = nullptr;
};

static bool edge_walker_contains(BMesh *bm,
                                 const int walker_type,
                                 BMEdge *source,
                                 const BMEdge *destination,
                                 const BMWDelimitFlag delimit)
{
  BMWalker walker;
  BMW_init(&walker,
           bm,
           walker_type,
           BMW_MASK_NOP,
           BMW_MASK_NOP,
           BMW_MASK_NOP,
           BMW_FLAG_TEST_HIDDEN,
           BMW_NIL_LAY,
           delimit);

  bool contains = false;
  BMEdge *edge;
  BMW_ITER (edge, &walker, source) {
    if (edge == destination) {
      contains = true;
      break;
    }
  }
  BMW_end(&walker);
  return contains;
}

static bool edges_are_opposite_in_quad(BMEdge *source, BMEdge *destination)
{
  if (source == destination || BM_edge_share_vert_check(source, destination)) {
    return false;
  }

  BMIter iter;
  BMFace *face;
  BM_ITER_ELEM (face, &iter, source, BM_FACES_OF_EDGE) {
    if (face->len == 4 && BM_edge_in_face(destination, face)) {
      return true;
    }
  }
  return false;
}

static MayaEdgePathPick edge_path_pick_from_event(bContext *C, const wmEvent &event)
{
  MayaEdgePathPick result;
  ViewContext vc = em_setup_viewcontext(C);
  copy_v2_v2_int(vc.mval, event.mval);
  view3d_operator_needs_gpu(C);

  BMVert *vertex = nullptr;
  BMEdge *edge = nullptr;
  BMFace *face = nullptr;
  int base_index = -1;
  Vector<Base *> bases = BKE_view_layer_array_from_bases_in_edit_mode(
      *vc.bmain, vc.scene, vc.view_layer, vc.v3d);
  if (!EDBM_unified_findnearest(
          &vc, bases, &base_index, &vertex, &edge, &face) ||
      edge == nullptr || base_index < 0)
  {
    return result;
  }

  Object *object = bases[base_index]->object;
  result.edit_mesh = BKE_editmesh_from_object(object);
  BMElem *active = BM_mesh_active_elem_get(result.edit_mesh->bm);
  if (active == nullptr || active->head.htype != BM_EDGE) {
    result.edit_mesh = nullptr;
    return result;
  }

  result.source = reinterpret_cast<BMEdge *>(active);
  result.destination = edge;
  return result;
}

MayaTopologySelectOp topology_select_op_from_action(const MayaInputAction &action)
{
  if (action.ctrl && action.shift) {
    return MayaTopologySelectOp::Add;
  }
  if (action.ctrl) {
    return MayaTopologySelectOp::Subtract;
  }
  if (action.shift) {
    return MayaTopologySelectOp::Toggle;
  }
  return MayaTopologySelectOp::Replace;
}

/**
 * Whether a previously selected component can act as the start of a path.
 *
 * Maya takes the last selected component as the beginning of the gesture. Without one there is
 * nothing to walk towards, and the very same double click selects the whole loop instead, which is
 * what a bare `MESH_OT_shortest_path_pick` gets wrong: with no active element it toggles the single
 * component under the pointer.
 */
static bool has_path_source_component(bContext *C)
{
  Object *object = CTX_data_edit_object(C);
  BMEditMesh *em = object != nullptr ? BKE_editmesh_from_object(object) : nullptr;
  if (em == nullptr || em->bm == nullptr) {
    return false;
  }
  const BMElem *active = BM_mesh_active_elem_get(em->bm);
  if (active == nullptr) {
    return false;
  }
  switch (active->head.htype) {
    case BM_VERT:
      return (em->selectmode & SCE_SELECT_VERTEX) != 0;
    case BM_EDGE:
      return (em->selectmode & SCE_SELECT_EDGE) != 0;
    case BM_FACE:
      return (em->selectmode & SCE_SELECT_FACE) != 0;
    default:
      return false;
  }
}

/** Selected components across every mesh being edited: the cheapest measure of what an operator did. */
static int edit_mesh_selected_count(bContext *C)
{
  int count = 0;
  for (Object *object : edit_mesh_objects_get(C)) {
    const BMEditMesh *em = BKE_editmesh_from_object(object);
    if (em == nullptr || em->bm == nullptr) {
      continue;
    }
    count += em->bm->totvertsel + em->bm->totedgesel + em->bm->totfacesel;
  }
  return count;
}

/** Set the three selection properties every loop and ring operator shares. */
static void topology_select_op_properties_set(PointerRNA *ptr, const MayaTopologySelectOp op)
{
  RNA_boolean_set(ptr, "extend", op == MayaTopologySelectOp::Add);
  RNA_boolean_set(ptr, "deselect", op == MayaTopologySelectOp::Subtract);
  RNA_boolean_set(ptr, "toggle", op == MayaTopologySelectOp::Toggle);
}

static wmOperatorStatus select_loop_call(bContext *C,
                                         const MayaInputAction &action,
                                         const MayaTopologySelectOp op)
{
  wmOperatorType *ot = WM_operatortype_find("MESH_OT_loop_select", true);
  PointerRNA ptr = WM_operator_properties_create_ptr(ot);
  topology_select_op_properties_set(&ptr, op);
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::InvokeDefault, &ptr, action.source_event);
  WM_operator_properties_free(&ptr);
  return status;
}

static wmOperatorStatus select_path_call(bContext *C,
                                         const MayaInputAction &action,
                                         const MayaTopologySelectOp op)
{
  MayaEdgePathPick edge_pick = edge_path_pick_from_event(C, *action.source_event);
  if (edge_pick.edit_mesh != nullptr &&
      edges_are_opposite_in_quad(edge_pick.source, edge_pick.destination))
  {
    wmOperatorType *ot = WM_operatortype_find("MESH_OT_edgering_select", true);
    PointerRNA ptr = WM_operator_properties_create_ptr(ot);
    topology_select_op_properties_set(&ptr, op);
    const wmOperatorStatus status = WM_operator_name_call_ptr(
        C, ot, wm::OpCallContext::InvokeDefault, &ptr, action.source_event);
    WM_operator_properties_free(&ptr);
    return status;
  }

  bool use_face_step = false;
  if (edge_pick.edit_mesh != nullptr) {
    BMesh *bm = edge_pick.edit_mesh->bm;
    const bool is_loop = edge_walker_contains(bm,
                                              BMW_EDGELOOP,
                                              edge_pick.source,
                                              edge_pick.destination,
                                              BMWDelimitFlag(
                                                  BMW_DELIMIT_EDGE_LOOP_OUTER_CORNERS |
                                                  BMW_DELIMIT_EDGE_LOOP_NGONS));
    const bool is_ring = edge_walker_contains(bm,
                                              BMW_EDGERING,
                                              edge_pick.source,
                                              edge_pick.destination,
                                              BMW_DELIMIT_EDGE_RING_NGONS);
    use_face_step = is_ring && !is_loop;
  }

  wmOperatorType *ot = WM_operatortype_find("MESH_OT_shortest_path_pick", true);
  PointerRNA ptr = WM_operator_properties_create_ptr(ot);
  RNA_boolean_set(&ptr, "use_fill", false);
  RNA_boolean_set(&ptr, "use_face_step", use_face_step);

  /* This operator only toggles: it selects the path unless every one of its components is already
   * selected, in which case it deselects the whole path. It has no extend, deselect or toggle
   * property to ask for something else.
   *
   * Two toggles of one path therefore always end on "all deselected", and returning from there ends
   * on "all selected", which is exactly the guaranteed remove and the guaranteed add Maya offers. The
   * second call walks the very same path because `track_active` stays off, so the active element the
   * path starts from is left where it was.
   *
   * The undo push of both calls is suppressed and replaced with a single step: one gesture must cost
   * the user one undo. */
  wmWindowManager *wm = CTX_wm_manager(C);
  const bool needs_second_call = ELEM(op, MayaTopologySelectOp::Add, MayaTopologySelectOp::Subtract);
  const int selected_before = needs_second_call ? edit_mesh_selected_count(C) : 0;
  if (needs_second_call && wm != nullptr) {
    wm->op_undo_depth++;
  }
  wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::InvokeDefault, &ptr, action.source_event);
  if (needs_second_call && (status & OPERATOR_FINISHED)) {
    const int selected_after = edit_mesh_selected_count(C);
    const bool path_was_fully_selected = selected_after < selected_before;
    const bool toggle_went_the_wrong_way = op == MayaTopologySelectOp::Add ?
                                               path_was_fully_selected :
                                               !path_was_fully_selected;
    if (toggle_went_the_wrong_way) {
      status = WM_operator_name_call_ptr(
          C, ot, wm::OpCallContext::InvokeDefault, &ptr, action.source_event);
    }
  }
  if (needs_second_call && wm != nullptr) {
    wm->op_undo_depth--;
    if (status & OPERATOR_FINISHED) {
      ED_undo_push(C, op == MayaTopologySelectOp::Add ? "Add Select Path" : "Remove Select Path");
    }
  }
  WM_operator_properties_free(&ptr);
  return status;
}

MayaDispatchResult selection_handle_action(bContext *C,
                                            MayaWindowRuntime &runtime,
                                            const MayaInputAction &action)
{
  const ARegion *region = CTX_wm_region(C);
  const bool is_window_region = region != nullptr && region->regiontype == RGN_TYPE_WINDOW;
  if (!is_window_region &&
      ELEM(action.id,
           MayaActionID::SelectPrimary,
           MayaActionID::SelectAdd,
           MayaActionID::SelectRemove,
           MayaActionID::SelectToggle,
           MayaActionID::SelectTopology))
  {
    return MayaDispatchResult::PassThrough;
  }

  MayaComponentMode mode = MayaComponentMode::Object;
  bool is_mode_action = true;
  switch (action.id) {
    case MayaActionID::ToggleObjectComponent:
      mode = component_mode_from_context(C, runtime) == MayaComponentMode::Object ?
                 runtime.last_component_mode :
                 MayaComponentMode::Object;
      break;
    case MayaActionID::ComponentVertex:
      mode = MayaComponentMode::Vertex;
      break;
    case MayaActionID::ComponentEdge:
      mode = MayaComponentMode::Edge;
      break;
    case MayaActionID::ComponentFace:
      mode = MayaComponentMode::Face;
      break;
    case MayaActionID::ComponentUV:
      mode = MayaComponentMode::UV;
      break;
    case MayaActionID::ComponentVertexFace:
      mode = MayaComponentMode::VertexFace;
      break;
    case MayaActionID::ComponentMulti:
      mode = MayaComponentMode::Multi;
      break;
    default:
      is_mode_action = false;
      break;
  }
  if (is_mode_action) {
    const wmOperatorStatus status = component_mode_operator_call(C, mode);
    return (status & OPERATOR_FINISHED) ? MayaDispatchResult::Handled :
                                         MayaDispatchResult::PassThrough;
  }

  if (ELEM(action.id,
           MayaActionID::SelectPrimary,
           MayaActionID::SelectAdd,
           MayaActionID::SelectRemove,
           MayaActionID::SelectToggle))
  {
    eSelectOp select_op = SEL_OP_SET;
    if (action.id == MayaActionID::SelectAdd) {
      select_op = SEL_OP_ADD;
    }
    else if (action.id == MayaActionID::SelectRemove) {
      select_op = SEL_OP_SUB;
    }
    else if (action.id == MayaActionID::SelectToggle) {
      select_op = SEL_OP_XOR;
    }
    select_pick_call(C, action, select_op);
    return MayaDispatchResult::Handled;
  }

  if (action.id == MayaActionID::SelectTopology && is_mesh_component_context(C)) {
    const MayaTopologySelectOp op = topology_select_op_from_action(action);
    /* Replacing the selection has no start component to walk from by definition, so a plain double
     * click is always the whole loop. Every other operation continues the gesture from the component
     * selected before it, and only falls back to the loop when there is none. */
    const bool use_path = op != MayaTopologySelectOp::Replace && has_path_source_component(C);
    const wmOperatorStatus status = use_path ? select_path_call(C, action, op) :
                                              select_loop_call(C, action, op);
    return (status & OPERATOR_CANCELLED) ? MayaDispatchResult::PassThrough :
                                          MayaDispatchResult::Handled;
  }

  if (ELEM(action.id, MayaActionID::SelectGrow, MayaActionID::SelectShrink) &&
      is_mesh_component_context(C))
  {
    const char *operator_id = action.id == MayaActionID::SelectGrow ? "MESH_OT_select_more" :
                                                                     "MESH_OT_select_less";
    const wmOperatorStatus status = WM_operator_name_call(
        C, operator_id, wm::OpCallContext::ExecDefault, nullptr, nullptr);
    return (status & OPERATOR_CANCELLED) ? MayaDispatchResult::PassThrough :
                                          MayaDispatchResult::Handled;
  }

  return MayaDispatchResult::PassThrough;
}

/**
 * Whether this motion event is the one crossing of the drag threshold that belongs to \a button.
 *
 * Blender never queues a #KM_PRESS_DRAG event: it synthesizes one inside #wm_handlers_do, hands it to
 * that handler list and restores the event before returning, all of which happens after this
 * dispatcher has already seen the plain motion. What survives is
 * #wmWindow::event_queue_check_drag_handled, set on the single threshold crossing and cleared before
 * the next motion event, so it is what identifies a drag here.
 */
static bool is_drag_threshold_crossing(const MayaWindowRuntime &runtime,
                                       const MayaInputAction &action,
                                       const bContext *C,
                                       const wmEventType button)
{
  const wmEvent *event = action.source_event;
  const wmWindow *window = CTX_wm_window(C);
  return !runtime.transform_active && action.id == MayaActionID::PointerMove &&
         action.phase == MayaActionPhase::Update && !action.alt && event != nullptr &&
         window != nullptr && window->event_queue_check_drag_handled &&
         event->type == MOUSEMOVE && event->prev_press_type == button &&
         (event->prev_press_modifier & KM_ALT) == 0 &&
         ((event->flag & WM_EVENT_FORCE_DRAG_THRESHOLD) != 0 ||
          WM_event_drag_test(event, event->prev_press_xy));
}

bool left_mouse_marquee_drag_handle(bContext *C,
                                    MayaWindowRuntime &runtime,
                                    const MayaInputAction &action)
{
  if (!is_drag_threshold_crossing(runtime, action, C, LEFTMOUSE)) {
    return false;
  }
  /* Edit Pivot owns the left button while it is active: its click operator places the pivot, and a
   * drag there must not start selecting instead. */
  if (runtime.pivot_edit.target != MayaPivotEditTarget::None) {
    return false;
  }
  const ARegion *region = CTX_wm_region(C);
  if (region == nullptr || region->regiontype != RGN_TYPE_WINDOW) {
    return false;
  }

  /* Maya reads the modifiers of the press that started the drag, not of the motion that happens to
   * cross the threshold. */
  MayaInputAction drag = action;
  const wmEventModifierFlag modifier = action.source_event->prev_press_modifier;
  drag.shift = (modifier & KM_SHIFT) != 0;
  drag.ctrl = (modifier & KM_CTRL) != 0;
  drag.alt = false;

  /* The drag is consumed whatever the marquee answers: otherwise the tool keymap of Move, Rotate or
   * Scale inherits it and starts a transform where Maya draws a selection rectangle. */
  select_marquee_call(C, drag);
  return true;
}

bool middle_mouse_axis_drag_handle(bContext *C,
                                   MayaWindowRuntime &runtime,
                                   const MayaInputAction &action)
{
  if (!is_drag_threshold_crossing(runtime, action, C, MIDDLEMOUSE)) {
    return false;
  }
  /* The threshold check already refused an action without one, so this is never null. */
  const wmEvent *event = action.source_event;

  const char *operator_id = nullptr;
  switch (runtime.tool.active) {
    case MayaToolID::Move:
      operator_id = "TRANSFORM_OT_translate";
      break;
    case MayaToolID::Rotate:
      operator_id = "TRANSFORM_OT_rotate";
      break;
    case MayaToolID::Scale:
      operator_id = "TRANSFORM_OT_resize";
      break;
    default:
      /* The original MMB press was consumed before regional keymaps. Consume its synthetic drag
       * too, so Select and other tools cannot inherit an unrelated MMB binding. */
      return true;
  }

  const int active_axis = runtime.tool.manipulator_pivot.active_axis;
  if (active_axis < 0 || active_axis > 2) {
    return true;
  }

  wmOperatorType *ot = WM_operatortype_find(operator_id, true);
  if (ot == nullptr) {
    return true;
  }
  PointerRNA ptr = WM_operator_properties_create_ptr(ot);

  const bool edit_pivot = runtime.pivot_edit.target != MayaPivotEditTarget::None;
  PropertyRNA *maya_pivot_transform = RNA_struct_find_property(&ptr, "maya_pivot_transform");
  if (edit_pivot && maya_pivot_transform == nullptr) {
    /* Edit Pivot must never fall back to transforming the object. */
    WM_operator_properties_free(&ptr);
    return true;
  }
  if (maya_pivot_transform != nullptr) {
    RNA_property_boolean_set(&ptr, maya_pivot_transform, edit_pivot);
  }

  bool constraint_axis[3] = {false, false, false};
  constraint_axis[active_axis] = true;
  RNA_boolean_set_array(&ptr, "constraint_axis", constraint_axis);
  RNA_boolean_set(&ptr, "release_confirm", true);

  float pivot_matrix[4][4];
  const bool has_custom_pivot_matrix = ED_maya_pivot_custom_matrix_get(
      C, MayaPivotUsage::Display, pivot_matrix);
  if (has_custom_pivot_matrix) {
    float orient_matrix[3][3];
    copy_m3_m4(orient_matrix, pivot_matrix);
    /* With orient_type left unset, a supplied matrix is the transform API's custom-matrix
     * orientation. This keeps the constraint on the visible Maya pivot axis. */
    RNA_float_set_array(&ptr, "orient_matrix", &orient_matrix[0][0]);
  }

  if (runtime.tool.active == MayaToolID::Scale) {
    const RegionView3D *region_view = CTX_wm_region_view3d(C);
    const float (*display_matrix)[4] = nullptr;
    if (has_custom_pivot_matrix) {
      display_matrix = pivot_matrix;
    }
    else if (region_view != nullptr) {
      display_matrix = region_view->twmat;
    }
    if (display_matrix != nullptr) {
      RNA_float_set_array(&ptr, "mouse_dir_constraint", display_matrix[active_axis]);
      RNA_boolean_set(&ptr, "use_maya_scale_behavior", true);
    }
  }

  wmEvent invoke_event = *event;
  invoke_event.type = MIDDLEMOUSE;
  invoke_event.val = KM_PRESS_DRAG;
  invoke_event.modifier = event->prev_press_modifier;
  invoke_event.keymodifier = event->prev_press_keymodifier;
  WM_operator_name_call_ptr(C, ot, wm::OpCallContext::InvokeDefault, &ptr, &invoke_event);
  WM_operator_properties_free(&ptr);
  /* Once the press was claimed, never let a cancelled operator fall through to regional MMB
   * keymaps and start a different action. */
  return true;
}

static Vector<Object *> selected_objects_get(const bContext *C)
{
  const Main *bmain = CTX_data_main(C);
  const Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);
  BKE_view_layer_synced_ensure(*bmain, scene, view_layer);

  Vector<Object *> objects;
  for (Base &base : *BKE_view_layer_object_bases_get(view_layer)) {
    if (base.flag & BASE_SELECTED) {
      objects.append(base.object);
    }
  }
  return objects;
}

static bool shift_transform_is_gizmo_drag(const MayaWindowRuntime &runtime,
                                          wmOperator *op,
                                          const wmEvent &event)
{
  if ((!runtime.selection_settings.shift_extrude &&
       !runtime.selection_settings.shift_duplicate) ||
      runtime.pivot_edit.target != MayaPivotEditTarget::None)
  {
    return false;
  }
  if (!ELEM(runtime.tool.active, MayaToolID::Move, MayaToolID::Rotate, MayaToolID::Scale)) {
    return false;
  }
  if (event.type != LEFTMOUSE || event.val != KM_PRESS || (event.modifier & KM_SHIFT) == 0 ||
      (event.modifier & KM_ALT) != 0)
  {
    return false;
  }
  if (!(STREQ(op->type->idname, "TRANSFORM_OT_translate") ||
        STREQ(op->type->idname, "TRANSFORM_OT_rotate") ||
        STREQ(op->type->idname, "TRANSFORM_OT_trackball") ||
        STREQ(op->type->idname, "TRANSFORM_OT_resize")))
  {
    return false;
  }
  PropertyRNA *release_confirm = RNA_struct_find_property(op->ptr, "release_confirm");
  return release_confirm != nullptr && RNA_property_boolean_get(op->ptr, release_confirm);
}

static void shift_transform_edit_backups_free(MayaShiftTransformState &state)
{
  for (MayaEditMeshBackup &item : state.edit_mesh_backups) {
    EDBM_redo_state_free(&item.backup);
  }
  state.edit_mesh_backups.clear();
}

static bool shift_transform_object_duplicate(bContext *C,
                                             MayaWindowRuntime &runtime,
                                             MayaShiftTransformState &state)
{
  state.source_objects = selected_objects_get(C);
  if (state.source_objects.is_empty()) {
    return false;
  }

  ViewLayer *view_layer = CTX_data_view_layer(C);
  Base *active_base = BKE_view_layer_active_base_get(view_layer);
  state.active_source = active_base != nullptr ? active_base->object : nullptr;

  wmOperatorType *ot = WM_operatortype_find("OBJECT_OT_duplicate", true);
  PointerRNA ptr = WM_operator_properties_create_ptr(ot);
  RNA_boolean_set(&ptr, "linked", runtime.selection_settings.shift_duplicate_linked);
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::ExecDefault, &ptr, nullptr);
  WM_operator_properties_free(&ptr);
  if (!(status & OPERATOR_FINISHED)) {
    return false;
  }

  if (!runtime.selection_settings.shift_duplicate_linked) {
    wmOperatorType *single_user_ot = WM_operatortype_find("OBJECT_OT_make_single_user", true);
    PointerRNA single_user_ptr = WM_operator_properties_create_ptr(single_user_ot);
    RNA_enum_set(&single_user_ptr, "type", 2);
    RNA_boolean_set(&single_user_ptr, "object", false);
    RNA_boolean_set(&single_user_ptr, "obdata", true);
    RNA_boolean_set(&single_user_ptr, "material", false);
    RNA_boolean_set(&single_user_ptr, "animation", false);
    RNA_boolean_set(&single_user_ptr, "obdata_animation", false);
    WM_operator_name_call_ptr(
        C, single_user_ot, wm::OpCallContext::ExecDefault, &single_user_ptr, nullptr);
    WM_operator_properties_free(&single_user_ptr);
  }

  for (Object *object : selected_objects_get(C)) {
    if (!state.source_objects.contains(object)) {
      state.result_objects.append(object);
      if (!runtime.selection_settings.shift_duplicate_linked && object->data != nullptr) {
        ID *data = static_cast<ID *>(object->data);
        if (!state.result_data.contains(data)) {
          state.result_data.append(data);
        }
      }
    }
  }
  return !state.result_objects.is_empty();
}

static bool shift_transform_component_extrude(bContext *C,
                                              MayaWindowRuntime &runtime,
                                              MayaShiftTransformState &state)
{
  Vector<Object *> objects = edit_mesh_objects_get(C);
  if (objects.is_empty()) {
    return false;
  }
  bool has_selection = false;
  for (Object *object : objects) {
    const BMEditMesh *em = BKE_editmesh_from_object(object);
    has_selection |= em != nullptr && em->bm != nullptr && em->bm->totvertsel != 0;
  }
  if (!has_selection) {
    return false;
  }
  for (Object *object : objects) {
    BMEditMesh *em = BKE_editmesh_from_object(object);
    state.edit_mesh_backups.append({object, EDBM_redo_state_store(em)});
  }

  const BMEditMesh *active_em = BKE_editmesh_from_object(CTX_data_edit_object(C));
  const int select_mode = active_em->selectmode;
  const char *operator_id = "MESH_OT_extrude_region";
  if (select_mode == SCE_SELECT_VERTEX) {
    operator_id = "MESH_OT_extrude_verts_indiv";
  }
  else if (select_mode == SCE_SELECT_EDGE) {
    operator_id = "MESH_OT_extrude_edges_indiv";
  }
  else if (select_mode == SCE_SELECT_FACE && !runtime.selection_settings.keep_faces_together) {
    operator_id = "MESH_OT_extrude_faces_indiv";
  }

  const wmOperatorStatus status = WM_operator_name_call(
      C, operator_id, wm::OpCallContext::ExecDefault, nullptr, nullptr);
  if (!(status & OPERATOR_FINISHED)) {
    shift_transform_edit_backups_free(state);
    return false;
  }
  return true;
}

bool shift_transform_prepare(bContext *C, wmOperator *op, const wmEvent *event)
{
  if (op == nullptr || event == nullptr || !ED_maya_interaction_enabled(C)) {
    return false;
  }
  MayaWindowRuntime *runtime = runtime_get(C);
  if (runtime == nullptr || runtime->shift_transform ||
      !shift_transform_is_gizmo_drag(*runtime, op, *event))
  {
    return false;
  }

  std::shared_ptr<MayaShiftTransformState> state = std::make_shared<MayaShiftTransformState>();
  state->scene = CTX_data_scene(C);
  state->view_layer = CTX_data_view_layer(C);

  /* Which of the two settings has a say depends on what the drag would create, so the gate sits
   * here and not in #shift_transform_is_gizmo_drag, which runs before that is known. */
  bool prepared = false;
  Object *edit_object = CTX_data_edit_object(C);
  if (edit_object != nullptr && edit_object->type == OB_MESH) {
    if (runtime->selection_settings.shift_extrude) {
      state->kind = MayaShiftTransformState::Kind::ComponentExtrude;
      prepared = shift_transform_component_extrude(C, *runtime, *state);
    }
  }
  else if (CTX_data_mode_enum(C) == CTX_MODE_OBJECT) {
    if (runtime->selection_settings.shift_duplicate) {
      state->kind = MayaShiftTransformState::Kind::ObjectDuplicate;
      prepared = shift_transform_object_duplicate(C, *runtime, *state);
    }
  }

  if (prepared) {
    runtime->shift_transform = std::move(state);
  }
  return prepared;
}

static void shift_transform_object_restore(bContext *C, MayaShiftTransformState &state)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = state.scene ? state.scene : CTX_data_scene(C);
  ViewLayer *view_layer = state.view_layer ? state.view_layer : CTX_data_view_layer(C);

  for (Object *object : state.result_objects) {
    ed::object::base_free_and_unlink_no_indirect_check(bmain, scene, object);
  }
  for (ID *data : state.result_data) {
    if (ID_REAL_USERS(data) == 0) {
      BKE_id_delete(bmain, data);
    }
  }

  BKE_view_layer_synced_ensure(*bmain, scene, view_layer);
  for (Base &base : *BKE_view_layer_object_bases_get(view_layer)) {
    ed::object::base_select(&base, ed::object::BA_DESELECT);
  }
  for (Object *object : state.source_objects) {
    if (Base *base = BKE_view_layer_base_find(view_layer, object)) {
      ed::object::base_select(base, ed::object::BA_SELECT);
    }
  }
  if (state.active_source != nullptr) {
    if (Base *base = BKE_view_layer_base_find(view_layer, state.active_source)) {
      ed::object::base_activate(C, base);
    }
  }

  DEG_relations_tag_update(bmain);
  DEG_id_tag_update(&scene->id, ID_RECALC_SYNC_TO_EVAL | ID_RECALC_SELECT);
  WM_event_add_notifier(C, NC_SCENE | ND_OB_SELECT, scene);
  WM_event_add_notifier(C, NC_SCENE | ND_LAYER_CONTENT, scene);
}

static void shift_transform_component_restore(MayaShiftTransformState &state)
{
  for (MayaEditMeshBackup &item : state.edit_mesh_backups) {
    BMEditMesh *em = BKE_editmesh_from_object(item.object);
    if (em == nullptr) {
      EDBM_redo_state_free(&item.backup);
      continue;
    }
    EDBM_redo_state_restore_and_free(&item.backup, em, true);
    EDBMUpdate_Params params{};
    params.calc_looptris = true;
    params.calc_normals = true;
    params.is_destructive = true;
    EDBM_update(id_cast<Mesh *>(item.object->data), &params);
  }
  state.edit_mesh_backups.clear();
}

void shift_transform_end(bContext *C, MayaWindowRuntime &runtime, const bool cancelled)
{
  if (!runtime.shift_transform) {
    return;
  }

  MayaShiftTransformState &state = *runtime.shift_transform;
  if (cancelled) {
    if (state.kind == MayaShiftTransformState::Kind::ObjectDuplicate) {
      shift_transform_object_restore(C, state);
    }
    else {
      shift_transform_component_restore(state);
    }
  }
  else if (state.kind == MayaShiftTransformState::Kind::ComponentExtrude) {
    shift_transform_edit_backups_free(state);
  }
  runtime.shift_transform.reset();
}

}  // namespace blender::ed::maya

namespace blender {

bool ED_maya_shift_transform_prepare(bContext *C, wmOperator *op, const wmEvent *event)
{
  return ed::maya::shift_transform_prepare(C, op, event);
}

}  // namespace blender
