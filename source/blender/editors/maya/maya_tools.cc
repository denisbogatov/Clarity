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
#include "BLI_time.h"
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
               int(MayaCameraBasedSelection::Auto),
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

bool camera_based_selection_use_depth(const MayaCameraBasedSelection mode,
                                      const bool is_shaded,
                                      const bool is_xray)
{
  if (is_xray) {
    return false;
  }
  switch (mode) {
    case MayaCameraBasedSelection::Off:
      return false;
    case MayaCameraBasedSelection::On:
      return true;
    case MayaCameraBasedSelection::Auto:
      return is_shaded;
  }
  BLI_assert_unreachable();
  return false;
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
  /* Every Maya marquee operation uses the projected face area, not its center: replace, toggle,
   * subtract and add therefore agree even when the rectangle lies wholly inside a large face. */
  RNA_boolean_set(&ptr, "face_region_overlap", true);
  /* The marquee is started from the motion that crossed the drag threshold, so the event handed to
   * #WM_gesture_box_invoke is a mouse move rather than a press. Left at its default, `wait_for_input`
   * would then make it open a #WM_GESTURE_CROSS_RECT: a full-viewport dashed cross waiting for a
   * separate click that can never come, because the button is already held and will only be
   * released. The rectangle has to begin at the press position right away. */
  RNA_boolean_set(&ptr, "wait_for_input", false);
  bool use_depth = false;
  const MayaWindowRuntime *runtime = runtime_get(C);
  if (runtime != nullptr) {
    const View3D *v3d = CTX_wm_view3d(C);
    if (v3d != nullptr) {
      use_depth = camera_based_selection_use_depth(
          runtime->selection_settings.camera_based_selection,
          v3d->shading.type > OB_WIRE,
          XRAY_FLAG_ENABLED(v3d));
    }
  }
  RNA_boolean_set(&ptr, "use_depth", use_depth);
  if (ED_maya_gizmo_trace_enabled()) {
    /* Whether the marquee reaches behind the surface is decided from three pieces of state that
     * are invisible in the result: the setting, the shading mode and X-Ray. Naming them here is
     * what tells "the setting is off" apart from "X-Ray is on". */
    const View3D *v3d = CTX_wm_view3d(C);
    fprintf(stderr,
            "MARQUEE %.3f use_depth=%d setting=%d shading=%d xray=%d\n",
            BLI_time_now_seconds(),
            int(use_depth),
            runtime != nullptr ? int(runtime->selection_settings.camera_based_selection) : -1,
            v3d != nullptr ? int(v3d->shading.type) : -1,
            v3d != nullptr ? int(XRAY_FLAG_ENABLED(v3d)) : -1);
    fflush(stderr);
  }
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

struct MayaAdjacentFacePick {
  Object *object = nullptr;
  BMEditMesh *edit_mesh = nullptr;
  BMFace *destination = nullptr;
  BMEdge *shared_edge = nullptr;
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

/**
 * Whether the edge loop through this edge is the edge and nothing else.
 *
 * Blender ends a loop at any vertex that is not four-valence, so on a box every corner stops it and
 * the loop of an upright edge is that one edge. Maya's double click on the same edge selects all
 * four uprights, which is Blender's edge *ring*. Rather than guess which the user meant, measure:
 * a loop worth having has more than one edge in it, and where it does not, the ring is the answer
 * that matches Maya.
 */
static bool edge_loop_is_degenerate(BMesh *bm, BMEdge *edge)
{
  BMWalker walker;
  BMW_init(&walker,
           bm,
           BMW_EDGELOOP,
           BMW_MASK_NOP,
           BMW_MASK_NOP,
           BMW_MASK_NOP,
           BMW_FLAG_TEST_HIDDEN,
           BMW_NIL_LAY,
           BMWDelimitFlag(BMW_DELIMIT_EDGE_LOOP_OUTER_CORNERS | BMW_DELIMIT_EDGE_LOOP_NGONS));

  int count = 0;
  BMEdge *walked;
  BMW_ITER (walked, &walker, edge) {
    UNUSED_VARS(walked);
    count++;
    if (count > 1) {
      break;
    }
  }
  BMW_end(&walker);
  return count <= 1;
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

/**
 * The two ends of an edge gesture: the edge that was selected before the click, and the one under
 * the pointer. The source is handed in rather than read from the mesh, because by the time a double
 * click is handled the opening click has already made the destination the active edge.
 */
static MayaEdgePathPick edge_path_pick_from_event(bContext *C,
                                                  const wmEvent &event,
                                                  BMEdge *source)
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
  if (source == nullptr || source == edge) {
    result.edit_mesh = nullptr;
    return result;
  }

  result.source = source;
  result.destination = edge;
  return result;
}

/**
 * Remember the active face, before a click moves it.
 *
 * A double click always arrives behind the single click that opens it, and that click has already
 * made whatever is under the pointer the active face. Maya reads the pair - the face that was
 * selected, and the neighbor double clicked - to decide which way a face loop runs, so the first of
 * the two has to be kept before the click overwrites it. Held as an index rather than a pointer: an
 * index survives anything that reallocates the mesh, and it is checked against the object it came
 * from before it is used.
 */
/** Whether the select mode in force can act on components of this type. */
static bool selectmode_allows_htype(const short selectmode, const char htype)
{
  switch (htype) {
    case BM_VERT:
      return (selectmode & SCE_SELECT_VERTEX) != 0;
    case BM_EDGE:
      return (selectmode & SCE_SELECT_EDGE) != 0;
    case BM_FACE:
      return (selectmode & SCE_SELECT_FACE) != 0;
    default:
      return false;
  }
}

static void topology_anchor_store(bContext *C, MayaWindowRuntime &runtime)
{
  runtime.topology_anchor_object = nullptr;
  runtime.topology_anchor_index = -1;
  runtime.topology_anchor_htype = 0;

  Object *object = CTX_data_edit_object(C);
  BMEditMesh *em = object != nullptr ? BKE_editmesh_from_object(object) : nullptr;
  if (em == nullptr || em->bm == nullptr) {
    return;
  }
  BMElem *active = BM_mesh_active_elem_get(em->bm);
  if ((active == nullptr || !selectmode_allows_htype(em->selectmode, active->head.htype)) &&
      (em->selectmode & SCE_SELECT_FACE))
  {
    /* The active face lives in `act_face`, not in the selection history, so a face selection that
     * never went through the history has no active element at all. Asking for it directly is what
     * keeps the anchor alive in face mode - without it the face loop gesture has no source and
     * quietly degrades to a one-face path. */
    active = reinterpret_cast<BMElem *>(BM_mesh_active_face_get(em->bm, true, true));
  }
  if (active == nullptr || !BM_elem_flag_test(active, BM_ELEM_SELECT) ||
      !selectmode_allows_htype(em->selectmode, active->head.htype))
  {
    return;
  }
  BM_mesh_elem_index_ensure(em->bm, BM_VERT | BM_EDGE | BM_FACE);
  runtime.topology_anchor_object = object;
  runtime.topology_anchor_index = BM_elem_index_get(active);
  runtime.topology_anchor_htype = active->head.htype;
}

/** The component a topology gesture runs from: the one that was selected before the click. */
static BMElem *topology_anchor_elem_get(bContext *C, const MayaWindowRuntime &runtime, BMesh *bm)
{
  const Object *object = CTX_data_edit_object(C);
  if (object == nullptr || object != runtime.topology_anchor_object ||
      runtime.topology_anchor_index < 0)
  {
    return nullptr;
  }
  const int index = runtime.topology_anchor_index;
  switch (runtime.topology_anchor_htype) {
    case BM_VERT:
      if (index < bm->totvert) {
        BM_mesh_elem_table_ensure(bm, BM_VERT);
        return reinterpret_cast<BMElem *>(BM_vert_at_index(bm, index));
      }
      break;
    case BM_EDGE:
      if (index < bm->totedge) {
        BM_mesh_elem_table_ensure(bm, BM_EDGE);
        return reinterpret_cast<BMElem *>(BM_edge_at_index(bm, index));
      }
      break;
    case BM_FACE:
      if (index < bm->totface) {
        BM_mesh_elem_table_ensure(bm, BM_FACE);
        return reinterpret_cast<BMElem *>(BM_face_at_index(bm, index));
      }
      break;
  }
  return nullptr;
}

/** The face a loop runs from: the one selected before the click, or the active one if none. */
static BMFace *topology_anchor_face_get(bContext *C, const MayaWindowRuntime &runtime, BMesh *bm)
{
  BMElem *anchor = topology_anchor_elem_get(C, runtime, bm);
  if (anchor != nullptr && anchor->head.htype == BM_FACE) {
    return reinterpret_cast<BMFace *>(anchor);
  }
  BMElem *active = BM_mesh_active_elem_get(bm);
  return active != nullptr && active->head.htype == BM_FACE ? reinterpret_cast<BMFace *>(active) :
                                                              nullptr;
}

/** The component under the pointer, in the terms the select mode is working in. */
static BMElem *topology_pick_elem_from_event(bContext *C,
                                             const wmEvent &event,
                                             BMEditMesh **r_edit_mesh)
{
  *r_edit_mesh = nullptr;
  ViewContext vc = em_setup_viewcontext(C);
  copy_v2_v2_int(vc.mval, event.mval);
  view3d_operator_needs_gpu(C);

  BMVert *vertex = nullptr;
  BMEdge *edge = nullptr;
  BMFace *face = nullptr;
  int base_index = -1;
  Vector<Base *> bases = BKE_view_layer_array_from_bases_in_edit_mode(
      *vc.bmain, vc.scene, vc.view_layer, vc.v3d);
  if (!EDBM_unified_findnearest(&vc, bases, &base_index, &vertex, &edge, &face) || base_index < 0) {
    return nullptr;
  }
  BMEditMesh *em = BKE_editmesh_from_object(bases[base_index]->object);
  if (em == nullptr || em->bm == nullptr) {
    return nullptr;
  }
  *r_edit_mesh = em;

  /* #EDBM_unified_findnearest only reports the types the select mode asked for, so the first one it
   * found is the one the gesture is about. */
  if (vertex != nullptr && (em->selectmode & SCE_SELECT_VERTEX)) {
    return reinterpret_cast<BMElem *>(vertex);
  }
  if (edge != nullptr && (em->selectmode & SCE_SELECT_EDGE)) {
    return reinterpret_cast<BMElem *>(edge);
  }
  if (face != nullptr && (em->selectmode & SCE_SELECT_FACE)) {
    return reinterpret_cast<BMElem *>(face);
  }
  return nullptr;
}

/** Find the shared edge that defines a face loop when double-clicking a neighbor. */
static MayaAdjacentFacePick adjacent_face_pick_from_event(bContext *C,
                                                          const MayaWindowRuntime &runtime,
                                                          const wmEvent &event)
{
  MayaAdjacentFacePick result;
  ViewContext vc = em_setup_viewcontext(C);
  copy_v2_v2_int(vc.mval, event.mval);
  view3d_operator_needs_gpu(C);

  BMVert *vertex = nullptr;
  BMEdge *edge = nullptr;
  BMFace *face = nullptr;
  int base_index = -1;
  Vector<Base *> bases = BKE_view_layer_array_from_bases_in_edit_mode(
      *vc.bmain, vc.scene, vc.view_layer, vc.v3d);
  if (!EDBM_unified_findnearest(&vc, bases, &base_index, &vertex, &edge, &face) || face == nullptr ||
      base_index < 0)
  {
    return result;
  }

  result.object = bases[base_index]->object;
  result.edit_mesh = BKE_editmesh_from_object(result.object);
  if (result.edit_mesh == nullptr || result.edit_mesh->bm == nullptr) {
    return {};
  }
  BMFace *source = topology_anchor_face_get(C, runtime, result.edit_mesh->bm);
  if (source == nullptr || source == face) {
    return {};
  }
  BMIter iter;
  BM_ITER_ELEM (edge, &iter, source, BM_EDGES_OF_FACE) {
    if (BM_edge_in_face(edge, face)) {
      result.destination = face;
      result.shared_edge = edge;
      break;
    }
  }
  return result;
}

bool selection_action_is_reserved_for_marquee(const MayaInputAction &action)
{
  /* The additive marquee owns the `Ctrl Shift` drag, and a click of that chord that never became a
   * drag has to be swallowed rather than fall back to picking one component.
   *
   * A double click of the same chord is a different gesture: `Ctrl Shift` is how Maya says "add to
   * the selection", so it is how a loop is added to one already there. Swallowing it here is what
   * kept every downstream branch - the edge loop, the face loop, the path - from ever running, and
   * left the base keymap's own `Ctrl Shift` press binding as the only thing that answered. */
  return action.id == MayaActionID::SelectAddMarquee;
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
static bool has_path_source_component(bContext *C, const MayaWindowRuntime &runtime)
{
  Object *object = CTX_data_edit_object(C);
  BMEditMesh *em = object != nullptr ? BKE_editmesh_from_object(object) : nullptr;
  if (em == nullptr || em->bm == nullptr) {
    return false;
  }
  /* The anchor, not the active component: the click that opened the double click has already made
   * the clicked component active, so asking the mesh would name the destination as the source and
   * every path would be one component long. */
  const BMElem *anchor = topology_anchor_elem_get(C, runtime, em->bm);
  return anchor != nullptr && selectmode_allows_htype(em->selectmode, anchor->head.htype);
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

/* -------------------------------------------------------------------- */
/** \name Selection Constraints
 *
 * Maya's `polySelectConstraint`: a standing rule about what a selection is allowed to contain.
 * Every constraint runs after the selection was made rather than instead of it, which is what lets
 * one rule serve a click, a marquee and a topology gesture alike.
 *
 * Border and Angle narrow a selection down; Edge Loop, Edge Ring and Shell grow it. Maya draws the
 * same line: the first two are properties a component either has or does not, the last three are
 * ways of walking outwards from what was picked.
 * \{ */

/** An edge on the border of the surface: exactly one face uses it. */
static bool edge_passes_border(const BMEdge *edge, float /*tolerance*/)
{
  return BM_edge_is_boundary(const_cast<BMEdge *>(edge));
}

/** An edge creased enough to count, measured the way Maya measures it: between its two faces. */
static bool edge_passes_angle(const BMEdge *edge, const float tolerance)
{
  BMEdge *edge_mut = const_cast<BMEdge *>(edge);
  if (!BM_edge_is_manifold(edge_mut)) {
    /* A border or a wire edge has no second face to make an angle with. Maya keeps those out of an
     * angle constraint rather than treating the missing face as a flat one. */
    return false;
  }
  return BM_edge_calc_face_angle(edge_mut) >= tolerance;
}

using MayaEdgePredicate = bool (*)(const BMEdge *edge, float tolerance);

/**
 * Drop everything the predicate rejects.
 *
 * The predicate is about edges, because that is what both narrowing constraints are really about.
 * A vertex survives while any edge at it survives, and a face while any of its edges does, which
 * is how the same rule reaches the other two component modes.
 */
static bool selection_filter_by_edge(bContext *C,
                                     const MayaEdgePredicate predicate,
                                     const float tolerance)
{
  bool changed_any = false;
  for (Object *object : edit_mesh_objects_get(C)) {
    BMEditMesh *em = BKE_editmesh_from_object(object);
    if (em == nullptr || em->bm == nullptr) {
      continue;
    }
    BMesh *bm = em->bm;
    bool changed = false;

    BMIter iter;
    BMEdge *edge;
    BM_ITER_MESH (edge, &iter, bm, BM_EDGES_OF_MESH) {
      if (BM_elem_flag_test(edge, BM_ELEM_SELECT) && !predicate(edge, tolerance)) {
        BM_edge_select_set(bm, edge, false);
        changed = true;
      }
    }

    BMVert *vert;
    BM_ITER_MESH (vert, &iter, bm, BM_VERTS_OF_MESH) {
      if (!BM_elem_flag_test(vert, BM_ELEM_SELECT)) {
        continue;
      }
      bool keep = false;
      BMIter edge_iter;
      BM_ITER_ELEM (edge, &edge_iter, vert, BM_EDGES_OF_VERT) {
        if (predicate(edge, tolerance)) {
          keep = true;
          break;
        }
      }
      if (!keep) {
        BM_vert_select_set(bm, vert, false);
        changed = true;
      }
    }

    BMFace *face;
    BM_ITER_MESH (face, &iter, bm, BM_FACES_OF_MESH) {
      if (!BM_elem_flag_test(face, BM_ELEM_SELECT)) {
        continue;
      }
      bool keep = false;
      BMIter loop_iter;
      BMLoop *loop;
      BM_ITER_ELEM (loop, &loop_iter, face, BM_LOOPS_OF_FACE) {
        if (predicate(loop->e, tolerance)) {
          keep = true;
          break;
        }
      }
      if (!keep) {
        BM_face_select_set(bm, face, false);
        changed = true;
      }
    }

    if (changed) {
      EDBM_selectmode_flush(em);
      DEG_id_tag_update(static_cast<ID *>(object->data), ID_RECALC_SELECT);
      WM_event_add_notifier(C, NC_GEOM | ND_SELECT, object->data);
      changed_any = true;
    }
  }
  return changed_any;
}

/** Grow the selection outwards, which the mesh operators already know how to do. */
static bool selection_grow_by_operator(bContext *C, const MayaSelectionConstraint constraint)
{
  const int before = edit_mesh_selected_count(C);
  if (before == 0) {
    /* Nothing to walk out from. */
    return false;
  }

  const char *operator_id = nullptr;
  switch (constraint) {
    case MayaSelectionConstraint::EdgeLoop:
      operator_id = "MESH_OT_select_edge_loop_multi";
      break;
    case MayaSelectionConstraint::EdgeRing:
      operator_id = "MESH_OT_select_edge_ring_multi";
      break;
    case MayaSelectionConstraint::Shell:
      operator_id = "MESH_OT_select_linked";
      break;
    default:
      BLI_assert_unreachable();
      return false;
  }

  const wmOperatorStatus status = WM_operator_name_call(
      C, operator_id, wm::OpCallContext::ExecDefault, nullptr, nullptr);
  return (status & OPERATOR_FINISHED) != 0;
}

/**
 * Apply the standing selection constraint to whatever was just selected.
 *
 * Safe to call after any selection: it returns immediately unless a constraint is on and a mesh is
 * being edited, so callers do not have to ask first.
 */
static bool selection_constraint_apply(bContext *C)
{
  const MayaWindowRuntime *runtime = runtime_get(C);
  if (runtime == nullptr) {
    return false;
  }
  const MayaSelectionConstraint constraint = runtime->selection_settings.selection_constraint;
  if (constraint == MayaSelectionConstraint::Off || !is_mesh_component_context(C)) {
    return false;
  }

  switch (constraint) {
    case MayaSelectionConstraint::Border:
      return selection_filter_by_edge(C, edge_passes_border, 0.0f);
    case MayaSelectionConstraint::Angle: {
      const wmWindowManager *wm = CTX_wm_manager(C);
      const float tolerance = wm != nullptr && wm->runtime != nullptr ?
                                  wm->runtime->maya_selection_constraint_angle :
                                  DEG2RADF(45.0f);
      return selection_filter_by_edge(C, edge_passes_angle, tolerance);
    }
    case MayaSelectionConstraint::EdgeLoop:
    case MayaSelectionConstraint::EdgeRing:
    case MayaSelectionConstraint::Shell:
      return selection_grow_by_operator(C, constraint);
    case MayaSelectionConstraint::Off:
      break;
  }
  return false;
}

/** \} */

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
  /* The click that opened the double click has already selected the component under the pointer,
   * so a toggle arrives with the seed of the loop switched on and takes the loop straight back off
   * again. Maya keeps this gesture additive, which is also what #select_adjacent_face_loop_call
   * does for the face loop. */
  const MayaTopologySelectOp loop_op = op == MayaTopologySelectOp::Toggle ?
                                           MayaTopologySelectOp::Add :
                                           op;

  /* On a box the loop of an upright edge is that edge alone, because every corner is a pole and
   * Blender stops there. Maya answers the same double click with all four uprights, which is the
   * edge ring. Where the loop has nothing to walk, the ring is what the gesture meant. */
  BMEditMesh *picked_mesh = nullptr;
  BMElem *picked = action.source_event != nullptr ?
                       topology_pick_elem_from_event(C, *action.source_event, &picked_mesh) :
                       nullptr;
  if (picked != nullptr && picked->head.htype == BM_EDGE && picked_mesh != nullptr &&
      edge_loop_is_degenerate(picked_mesh->bm, reinterpret_cast<BMEdge *>(picked)))
  {
    WM_operator_properties_free(&ptr);
    ot = WM_operatortype_find("MESH_OT_edgering_select", true);
    ptr = WM_operator_properties_create_ptr(ot);
  }

  topology_select_op_properties_set(&ptr, loop_op);
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::InvokeDefault, &ptr, action.source_event);
  WM_operator_properties_free(&ptr);
  return status;
}

/** Grow the face picked by the first click of a double click to its complete connected shell. */
static wmOperatorStatus select_face_shell_call(bContext *C)
{
  wmOperatorType *ot = WM_operatortype_find("MESH_OT_select_linked", true);
  PointerRNA ptr = WM_operator_properties_create_ptr(ot);
  /* A Maya shell is delimited only by disconnected topology, not by seams or other edge marks. */
  RNA_enum_set(&ptr, "delimit", 0);
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::ExecDefault, &ptr, nullptr);
  WM_operator_properties_free(&ptr);
  return status;
}

/** Add the face loop whose direction is established by two neighboring faces. */
static wmOperatorStatus select_adjacent_face_loop_call(bContext *C,
                                                       const MayaAdjacentFacePick &pick)
{
  const Main *bmain = CTX_data_main(C);
  const Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);
  Vector<Base *> bases = BKE_view_layer_array_from_bases_in_edit_mode(
      *bmain, scene, view_layer, nullptr);
  int object_index = -1;
  for (const int i : bases.index_range()) {
    if (bases[i]->object == pick.object) {
      object_index = i;
      break;
    }
  }
  if (object_index < 0) {
    return OPERATOR_CANCELLED;
  }

  BMesh *bm = pick.edit_mesh->bm;
  BM_mesh_elem_index_ensure(bm, BM_EDGE | BM_FACE);
  wmOperatorType *ot = WM_operatortype_find("MESH_OT_loop_select", true);
  PointerRNA ptr = WM_operator_properties_create_ptr(ot);
  /* The preceding Shift-click has already selected the neighbor and therefore its shared edge.
   * Toggle would immediately remove the requested loop, while Maya keeps this gesture additive. */
  topology_select_op_properties_set(&ptr, MayaTopologySelectOp::Add);
  RNA_int_set(&ptr, "object_index", object_index);
  RNA_int_set(&ptr, "edge_index", BM_elem_index_get(pick.shared_edge));
  RNA_int_set(&ptr, "face_index", BM_elem_index_get(pick.destination));
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::ExecDefault, &ptr, nullptr);
  WM_operator_properties_free(&ptr);
  return status;
}

static wmOperatorStatus select_path_call(bContext *C,
                                         const MayaWindowRuntime &runtime,
                                         const MayaInputAction &action,
                                         const MayaTopologySelectOp op)
{
  /* A path needs two distinct ends. The one it starts from is the component that was selected
   * before this gesture opened, so it is restored as the active component for the duration of the
   * call: #MESH_OT_shortest_path_pick reads the active component and nothing else, and the opening
   * click has already moved that onto the destination. Where there is no such component, or it is
   * the very one under the pointer, there is no path to walk and the gesture is the loop. */
  BMEditMesh *picked_mesh = nullptr;
  BMElem *destination = topology_pick_elem_from_event(C, *action.source_event, &picked_mesh);
  BMElem *anchor = picked_mesh != nullptr ?
                       topology_anchor_elem_get(C, runtime, picked_mesh->bm) :
                       nullptr;
  if (destination == nullptr || anchor == nullptr || anchor == destination ||
      anchor->head.htype != destination->head.htype)
  {
    return select_loop_call(C, action, op);
  }
  BM_select_history_store(picked_mesh->bm, anchor);

  MayaEdgePathPick edge_pick = anchor->head.htype == BM_EDGE ?
                                   edge_path_pick_from_event(C,
                                                             *action.source_event,
                                                             reinterpret_cast<BMEdge *>(anchor)) :
                                   MayaEdgePathPick{};
  if (edge_pick.edit_mesh != nullptr &&
      edges_are_opposite_in_quad(edge_pick.source, edge_pick.destination))
  {
    wmOperatorType *ot = WM_operatortype_find("MESH_OT_edgering_select", true);
    PointerRNA ptr = WM_operator_properties_create_ptr(ot);
    /* Additive for the same reason #select_loop_call is: the click that opened the double click has
     * already selected the edge under the pointer, so a toggle arrives with the seed of the ring
     * switched on and takes the ring straight back off. */
    topology_select_op_properties_set(&ptr,
                                      op == MayaTopologySelectOp::Toggle ?
                                          MayaTopologySelectOp::Add :
                                          op);
    const wmOperatorStatus status = WM_operator_name_call_ptr(
        C, ot, wm::OpCallContext::InvokeDefault, &ptr, action.source_event);
    WM_operator_properties_free(&ptr);
    return status;
  }

  if (anchor->head.htype == BM_EDGE) {
    /* An edge double click is the loop of the edge under the pointer, whatever else is selected.
     * The edge ring above is the one gesture that reads the pair; everything else takes the edge on
     * its own, so a second loop joins the first instead of the two being joined by a path of the
     * few edges that happen to lie between them. */
    return select_loop_call(C, action, op);
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

  /* Hand the active component back to the end the user just picked. `track_active` is off, so the
   * operator left it on the anchor, and a second gesture would then walk from the same old start
   * instead of continuing from where this one stopped. */
  if (status & OPERATOR_FINISHED) {
    BM_select_history_store(picked_mesh->bm, destination);
  }
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
           MayaActionID::SelectAddMarquee,
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

  if (selection_action_is_reserved_for_marquee(action)) {
    /* `Ctrl+Shift+LMB` is reserved for the additive marquee. Its drag was handled when it crossed
     * the threshold; a click without a drag must not pick components instead. */
    return MayaDispatchResult::Handled;
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
    /* Taken before the pick, which is about to move the active face onto whatever is clicked: the
     * double click that may follow needs to know where the selection was standing. */
    topology_anchor_store(C, runtime);
    select_pick_call(C, action, select_op);
    /* A click selects immediately, so the constraint can narrow or grow the result right here. */
    selection_constraint_apply(C);
    return MayaDispatchResult::Handled;
  }

  if (action.id == MayaActionID::SelectTopology && is_mesh_component_context(C)) {
    const MayaTopologySelectOp op = topology_select_op_from_action(action);
    /* The first click has already made the face under the pointer the sole selection, so growing
     * from that seed gives Maya's whole-shell result. Shift-double-clicking a neighboring face uses
     * their shared edge to establish the face-loop direction; non-neighbors still form a path. */
    const bool is_face_mode = component_mode_from_context(C, runtime) == MayaComponentMode::Face;
    const bool use_face_shell = op == MayaTopologySelectOp::Replace && is_face_mode;
    MayaAdjacentFacePick face_loop_pick;
    /* Every additive form of the gesture, not just `Shift`: `Ctrl Shift` is how Maya says "add to
     * the selection", so it has to reach the face loop too. Gated on `Toggle` alone it fell through
     * to the path, and the path between two neighbors is the neighbor - one face per double click
     * instead of the loop the user was drawing around the mesh. */
    if (is_face_mode && ELEM(op, MayaTopologySelectOp::Toggle, MayaTopologySelectOp::Add)) {
      face_loop_pick = adjacent_face_pick_from_event(C, runtime, *action.source_event);
    }
    const bool use_path = op != MayaTopologySelectOp::Replace &&
                          has_path_source_component(C, runtime);
    if (ED_maya_gizmo_trace_enabled()) {
      /* Which branch a topology gesture takes depends on state that is gone by the time the result
       * is visible - the anchor, the component mode, whether the two faces touch. Naming all of it
       * at the fork in the road is the difference between reading a log and guessing. */
      fprintf(stderr,
              "TOPOSEL %.3f op=%d face_mode=%d anchor=%c/%d shell=%d adjacent=%d path=%d\n",
              BLI_time_now_seconds(),
              int(op),
              int(is_face_mode),
              runtime.topology_anchor_htype ? runtime.topology_anchor_htype : '-',
              runtime.topology_anchor_index,
              int(use_face_shell),
              int(face_loop_pick.shared_edge != nullptr),
              int(use_path));
      fflush(stderr);
    }
    wmOperatorStatus status;
    if (use_face_shell) {
      status = select_face_shell_call(C);
    }
    else if (face_loop_pick.shared_edge != nullptr) {
      status = select_adjacent_face_loop_call(C, face_loop_pick);
    }
    else if (use_path) {
      status = select_path_call(C, runtime, action, op);
    }
    else {
      status = select_loop_call(C, action, op);
    }
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
  /* So does the manipulator, and it cannot defend itself here: the dispatcher runs before the region
   * handlers, so a drag claimed at this point never reaches the gizmo map at all. Without this the
   * manipulator is drawn but inert - every drag on a handle became a selection rectangle instead of
   * a transform. The highlight is what the gizmo map itself would test the press against, so asking
   * it is the same question the gizmo would have asked one step later. */
  if (WM_gizmomap_region_is_highlighted(CTX_wm_region(C))) {
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
  /* The marquee is modal, so there is nothing to constrain yet. */
  runtime.selection_constraint_pending = true;
  return true;
}

bool selection_constraint_apply_pending(bContext *C, MayaWindowRuntime &runtime)
{
  if (!runtime.selection_constraint_pending) {
    return false;
  }
  runtime.selection_constraint_pending = false;
  return selection_constraint_apply(C);
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

/** Why a drag was or was not taken to be a Shift Extrude, under `BLENDER_MAYA_GIZMO_TRACE`. */
static void shift_transform_trace(const char *verdict, wmOperator *op, const wmEvent &event)
{
  if (!ED_maya_gizmo_trace_enabled()) {
    return;
  }
  fprintf(stderr,
          "SHIFTX %.3f %s op=%s type=%d val=%d mod=%d\n",
          BLI_time_now_seconds(),
          verdict,
          op != nullptr ? op->type->idname : "-",
          int(event.type),
          event.val,
          int(event.modifier));
  fflush(stderr);
}

static bool shift_transform_is_gizmo_drag(const MayaWindowRuntime &runtime,
                                          wmOperator *op,
                                          const wmEvent &event)
{
  if ((!runtime.selection_settings.shift_extrude &&
       !runtime.selection_settings.shift_duplicate) ||
      runtime.pivot_edit.target != MayaPivotEditTarget::None)
  {
    shift_transform_trace("no: setting off or edit pivot", op, event);
    return false;
  }
  if (!ELEM(runtime.tool.active, MayaToolID::Move, MayaToolID::Rotate, MayaToolID::Scale)) {
    shift_transform_trace("no: tool is not move/rotate/scale", op, event);
    return false;
  }
  /* The manipulator is bound to a click-drag, so the press that reaches the transform operator
   * carries #KM_PRESS_DRAG rather than #KM_PRESS. Both are the same gesture as far as this is
   * concerned: the left button went down with `Shift` held. */
  if (event.type != LEFTMOUSE || !ELEM(event.val, KM_PRESS, KM_PRESS_DRAG) ||
      (event.modifier & KM_SHIFT) == 0 || (event.modifier & KM_ALT) != 0)
  {
    shift_transform_trace("no: not a shifted left press", op, event);
    return false;
  }
  if (!(STREQ(op->type->idname, "TRANSFORM_OT_translate") ||
        STREQ(op->type->idname, "TRANSFORM_OT_rotate") ||
        STREQ(op->type->idname, "TRANSFORM_OT_trackball") ||
        STREQ(op->type->idname, "TRANSFORM_OT_resize")))
  {
    shift_transform_trace("no: not a transform operator", op, event);
    return false;
  }
  PropertyRNA *release_confirm = RNA_struct_find_property(op->ptr, "release_confirm");
  const bool from_gizmo = release_confirm != nullptr &&
                          RNA_property_boolean_get(op->ptr, release_confirm);
  shift_transform_trace(from_gizmo ? "yes: gizmo drag" : "no: not a gizmo drag", op, event);
  return from_gizmo;
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

/**
 * Maya's Edge Slide transform constraint, served by Blender's own slide transforms.
 *
 * The constraint is not a snap: the component travels along the edges it already belongs to. That
 * is exactly what #TRANSFORM_OT_vert_slide and #TRANSFORM_OT_edge_slide do, so the drag is handed
 * to whichever of them fits the selection mode instead of being reimplemented. When neither can
 * run - no edges to slide along, or a selection they cannot use - nothing is claimed and the plain
 * translation goes ahead, where the snap plan still holds the component against the nearest edge.
 */
static bool transform_slide_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  if (op == nullptr || event == nullptr || !ED_maya_interaction_enabled(C)) {
    return false;
  }
  if (ED_maya_transform_constraint_get(C) != MayaTransformConstraint::Edge) {
    return false;
  }
  /* Only a translation slides; a rotation or a scale has nothing to slide along. */
  if (!STREQ(op->type->idname, "TRANSFORM_OT_translate")) {
    shift_transform_trace("slide no: not a translation", op, *event);
    return false;
  }
  const Object *edit_object = CTX_data_edit_object(C);
  if (edit_object == nullptr || edit_object->type != OB_MESH) {
    shift_transform_trace("slide no: not an edit mesh", op, *event);
    return false;
  }
  const BMEditMesh *em = BKE_editmesh_from_object(const_cast<Object *>(edit_object));
  if (em == nullptr || em->bm == nullptr || em->bm->totvertsel == 0) {
    shift_transform_trace("slide no: nothing selected", op, *event);
    return false;
  }

  /* A vertex slides along the edges that meet at it; an edge or a face slides between the loops
   * beside it. Maya makes the same split. */
  const bool by_vertex = (em->selectmode & SCE_SELECT_VERTEX) != 0;
  wmOperatorType *ot = WM_operatortype_find(
      by_vertex ? "TRANSFORM_OT_vert_slide" : "TRANSFORM_OT_edge_slide", true);
  if (ot == nullptr) {
    return false;
  }
  /* The drag ends when the button comes up, exactly like the translation it replaces. Without this
   * the slide would sit there waiting for a confirming click. */
  PointerRNA ptr = WM_operator_properties_create_ptr(ot);
  RNA_boolean_set(&ptr, "release_confirm", true);
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::InvokeDefault, &ptr, event);
  WM_operator_properties_free(&ptr);

  const bool took_it = (status & OPERATOR_RUNNING_MODAL) != 0;
  shift_transform_trace(took_it ? "slide yes: started" : "slide no: operator declined", op, *event);
  return took_it;
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

bool ED_maya_transform_slide_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  return ed::maya::transform_slide_invoke(C, op, event);
}

}  // namespace blender
