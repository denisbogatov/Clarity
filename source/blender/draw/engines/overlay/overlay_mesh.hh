/* SPDX-FileCopyrightText: 2024 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup overlay
 */

#pragma once

#include <cfloat>
#include <cmath>
#include <optional>
#include <string>

#include "BLI_array.hh"
#include "BLI_math_matrix.h"
#include "BLI_math_matrix.hh"
#include "BLI_vector.hh"

#include "BKE_colorband.hh"
#include "BKE_customdata.hh"
#include "BKE_editmesh.hh"
#include "BKE_layer.hh"
#include "BKE_mask.hh"
#include "BKE_mesh.hh"
#include "BKE_mesh_types.hh"
#include "BKE_paint.hh"
#include "BKE_soft_selection.hh"
#include "BKE_subdiv_modifier.hh"

#include "DEG_depsgraph_query.hh"

#include "DNA_brush_types.h"
#include "DNA_mask_types.h"
#include "DNA_mesh_types.h"
#include "DNA_userdef_types.h"

#include "ED_clarity.hh"
#include "ED_view3d.hh"

#include "GPU_capabilities.hh"

#include "draw_cache.hh"
#include "draw_cache_impl.hh"
#include "draw_manager_text.hh"
#include "overlay_base.hh"

namespace blender::draw::overlay {

constexpr int overlay_edit_text = V3D_OVERLAY_EDIT_EDGE_LEN | V3D_OVERLAY_EDIT_FACE_AREA |
                                  V3D_OVERLAY_EDIT_FACE_ANG | V3D_OVERLAY_EDIT_EDGE_ANG |
                                  V3D_OVERLAY_EDIT_INDICES;

inline bool clarity_face_centers_visible(const Object &object)
{
  const Object *object_orig = DEG_get_original(&object);
  return object_orig != nullptr && (object_orig->dtx & OB_DRAW_FACE_CENTERS) != 0;
}

/**
 * Highlight the mesh component under the pointer while Clarity Edit Pivot snapping is active.
 */
class ClarityPivotSnapPreview : Overlay {
 private:
  PassSimple ps_ = {"Clarity Pivot Snap Preview"};
  LinePrimitiveBuf lines_;
  /** Clarity fills a highlighted face as well as outlining it. */
  TrianglePrimitiveBuf faces_ = {SelectionType::DISABLED, "clarity_pivot_snap_preview_faces"};
  StorageVectorBuffer<VertexData> points_ = {"clarity_pivot_snap_preview_points"};

  ed::clarity::ClarityPivotSnapResult target_;
  /**
   * Clarity's pre-highlight orange, measured off a 2025 capture: the vertex marker, the edge and
   * the face outline are all `239, 99, 5`, and the face is filled with the same colour at low
   * alpha.
   *
   * Held linear, because that is what the overlay pipeline writes: handing it the sRGB numbers
   * displayed them as `237, 164, 52`, an amber that is not the colour Clarity uses.
   */
  float4 color_ = float4(0.863f, 0.127f, 0.0015f, 1.0f);
  bool object_synced_ = false;
  bool in_front_ = false;

  static bool object_matches(const Object &object, const Object &target)
  {
    if (&object == &target) {
      return true;
    }
    return DEG_get_original(&object) == DEG_get_original(&target);
  }

  std::optional<float4x4> matching_object_to_world(const ObjectRef &ob_ref) const
  {
    if (target_.object == nullptr || !object_matches(*ob_ref.object, *target_.object)) {
      return std::nullopt;
    }
    if (!target_.object_to_world.has_value()) {
      return ob_ref.object_to_world(0);
    }
    for (const int instance : IndexRange(ob_ref.instances_count())) {
      const float4x4 matrix = ob_ref.object_to_world(instance);
      if (math::is_equal(matrix, *target_.object_to_world, 1.0e-5f)) {
        return matrix;
      }
    }
    return std::nullopt;
  }

 public:
  ClarityPivotSnapPreview(const SelectionType selection_type)
      : lines_(selection_type, "clarity_pivot_snap_preview_lines")
  {
  }

  void begin_sync(Resources &res, const State &state) final
  {
    target_ = {};
    object_synced_ = false;
    in_front_ = false;
    lines_.clear();
    faces_.clear();
    points_.clear();

    enabled_ = state.is_space_v3d() && !state.hide_overlays && !state.is_depth_only_drawing &&
               !res.is_selection();
    if (!enabled_) {
      return;
    }

    const DRWContext *draw_ctx = DRW_context_get();
    enabled_ = draw_ctx != nullptr && draw_ctx->evil_C != nullptr &&
               ED_clarity_pivot_snap_preview_get(draw_ctx->evil_C, target_) &&
               target_.position_world.has_value() &&
               ELEM(target_.type,
                    ed::clarity::ClarityPivotSnapTargetType::Vertex,
                    ed::clarity::ClarityPivotSnapTargetType::Edge,
                    ed::clarity::ClarityPivotSnapTargetType::Face);
    if (!enabled_) {
      return;
    }

    /* A point marker belongs to a point. Appending it for every target drew a dot in the middle of
     * a hovered face, which is not something Clarity puts there: a face highlights as a face. */
    if (target_.type == ed::clarity::ClarityPivotSnapTargetType::Vertex) {
      const double3 &position = *target_.position_world;
      points_.append(VertexData{
          float4(float(position.x), float(position.y), float(position.z), 0.0f), color_});
    }
  }

  void object_sync(Manager & /*manager*/,
                   const ObjectRef &ob_ref,
                   Resources & /*res*/,
                   const State &state) final
  {
    if (!enabled_ || object_synced_ || ob_ref.object->type != OB_MESH) {
      return;
    }

    const std::optional<float4x4> object_to_world = matching_object_to_world(ob_ref);
    if (!object_to_world.has_value()) {
      return;
    }
    object_synced_ = true;
    in_front_ = state.use_in_front && (ob_ref.object->dtx & OB_DRAW_IN_FRONT);

    if (target_.type == ed::clarity::ClarityPivotSnapTargetType::Vertex ||
        target_.component_index < 0)
    {
      return;
    }

    const auto position_world = [&](const float3 &position) {
      return math::transform_point(*object_to_world, position);
    };

    Object *object_orig = DEG_get_original(ob_ref.object);
    BMEditMesh *edit_mesh = object_orig != nullptr ? BKE_editmesh_from_object(object_orig) :
                                                     nullptr;
    if (edit_mesh != nullptr) {
      if (target_.type == ed::clarity::ClarityPivotSnapTargetType::Edge) {
        const BMEdge *edge = BM_edge_at_index_find(edit_mesh->bm, target_.component_index);
        if (edge != nullptr) {
          lines_.append(
              position_world(float3(edge->v1->co)), position_world(float3(edge->v2->co)), color_);
        }
        return;
      }

      const BMFace *face = BM_face_at_index_find(edit_mesh->bm, target_.component_index);
      if (face == nullptr || face->len < 2) {
        return;
      }
      const BMLoop *loop_first = BM_FACE_FIRST_LOOP(face);
      const BMLoop *loop = loop_first;
      do {
        lines_.append(position_world(float3(loop->v->co)),
                      position_world(float3(loop->next->v->co)),
                      color_);
        if (loop != loop_first && loop->next != loop_first) {
          faces_.append(position_world(float3(loop_first->v->co)),
                        position_world(float3(loop->v->co)),
                        position_world(float3(loop->next->v->co)),
                        color_);
        }
        loop = loop->next;
      } while (loop != loop_first);
      return;
    }

    Mesh &mesh = DRW_object_get_data_for_drawing<Mesh>(*ob_ref.object);
    const Span<float3> positions = mesh.vert_positions();
    if (target_.type == ed::clarity::ClarityPivotSnapTargetType::Edge) {
      const Span<int2> edges = mesh.edges();
      if (!edges.index_range().contains(target_.component_index)) {
        return;
      }
      const int2 edge = edges[target_.component_index];
      if (!positions.index_range().contains(edge.x) || !positions.index_range().contains(edge.y)) {
        return;
      }
      lines_.append(position_world(positions[edge.x]), position_world(positions[edge.y]), color_);
      return;
    }

    const OffsetIndices<int> faces = mesh.faces();
    if (!faces.index_range().contains(target_.component_index)) {
      return;
    }
    const Span<int> corner_verts = mesh.corner_verts();
    const IndexRange face = faces[target_.component_index];
    if (face.size() < 2) {
      return;
    }
    const int vert_first = corner_verts[face[0]];
    for (const int i : IndexRange(face.size())) {
      const int vert = corner_verts[face[i]];
      const int vert_next = corner_verts[face[(i + 1) % face.size()]];
      if (!positions.index_range().contains(vert) || !positions.index_range().contains(vert_next))
      {
        continue;
      }
      lines_.append(position_world(positions[vert]), position_world(positions[vert_next]), color_);
      if (i > 0 && i + 1 < face.size() && positions.index_range().contains(vert_first)) {
        faces_.append(position_world(positions[vert_first]),
                      position_world(positions[vert]),
                      position_world(positions[vert_next]),
                      color_);
      }
    }
  }

  void end_sync(Resources &res, const State &state) final
  {
    if (!enabled_) {
      return;
    }

    ps_.init();
    ps_.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
    ps_.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
    {
      /* The fill Clarity puts under a highlighted face: the same colour, barely opaque. No depth
       * test, so it does not fight for depth with the very face it covers. */
      PassSimple::Sub &sub = ps_.sub("component_fill");
      sub.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_BLEND_ALPHA, state.clipping_plane_count);
      sub.shader_set(res.shaders->armature_wire.get());
      sub.push_constant("alpha", 0.14f);
      faces_.end_sync(sub);
    }
    {
      /* The highlight belongs to the component under the pointer, so it is drawn over the surface
       * it lies on rather than being half-swallowed by it. */
      PassSimple::Sub &sub = ps_.sub("component_outline");
      sub.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_BLEND_ALPHA, state.clipping_plane_count);
      sub.shader_set(res.shaders->armature_wire.get());
      sub.push_constant("alpha", 1.0f);
      lines_.end_sync(sub);
    }
    {
      PassSimple::Sub &sub = ps_.sub("snap_position");
      sub.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_BLEND_ALPHA, state.clipping_plane_count);
      sub.shader_set(res.shaders->extra_point.get());
      points_.push_update();
      sub.bind_ssbo("data_buf", &points_);
      sub.draw_procedural(GPU_PRIM_POINTS, 1, points_.size());
    }
  }

  void draw_line(Framebuffer &framebuffer, Manager &manager, View &view) final
  {
    if (!enabled_) {
      return;
    }

    GPU_framebuffer_bind(framebuffer);
    manager.submit(ps_, view);
  }

  bool is_in_front() const
  {
    return in_front_;
  }
};

/**
 * Maya softSelect's false-color component feedback.
 *
 * The CPU values intentionally use the same distance and curve implementation as Transform.
 * Edges are always drawn, as Maya documents; point markers are added only in vertex-select mode.
 */
class SoftSelectionFalseColor : Overlay {
 private:
  PassSimple ps_ = {"Soft Selection False Color"};
  LinePrimitiveBuf edges_ = {SelectionType::DISABLED, "soft_selection_false_color_edges"};
  PointPrimitiveBuf vertices_ = {SelectionType::DISABLED, "soft_selection_false_color_vertices"};

  SoftSelectionSettings settings_{};
  std::optional<bke::SoftSelectionCurve> curve_;
  bke::SoftSelectionSpatialIndex *global_selected_index_ = nullptr;
  bool show_vertices_ = false;
  bool xray_flag_enabled_ = false;

  void free_global_index()
  {
    bke::soft_selection_spatial_index_free(global_selected_index_);
    global_selected_index_ = nullptr;
  }

  static bool selected_visible(const BMVert &vert)
  {
    return BM_elem_flag_test(&vert, BM_ELEM_SELECT) && !BM_elem_flag_test(&vert, BM_ELEM_HIDDEN);
  }

  void build_global_selected_index(const State &state)
  {
    BKE_view_layer_synced_ensure(
        *DEG_get_bmain(state.depsgraph), state.scene, const_cast<ViewLayer *>(state.view_layer));
    const Vector<Object *> objects = BKE_view_layer_array_from_objects_in_edit_mode_unique_data(
        *DEG_get_bmain(state.depsgraph),
        state.scene,
        const_cast<ViewLayer *>(state.view_layer),
        state.v3d);

    Vector<float3> selected_positions;
    for (Object *object : objects) {
      if (object->type != OB_MESH) {
        continue;
      }
      const BMEditMesh *edit_mesh = BKE_editmesh_from_object(object);
      if (edit_mesh == nullptr) {
        continue;
      }
      const float4x4 object_to_world = object->object_to_world();
      BMIter iter;
      BMVert *vert;
      BM_ITER_MESH (vert, &iter, edit_mesh->bm, BM_VERTS_OF_MESH) {
        if (selected_visible(*vert)) {
          selected_positions.append(math::transform_point(object_to_world, float3(vert->co)));
        }
      }
    }
    global_selected_index_ = bke::soft_selection_spatial_index_create(selected_positions);
  }

  static bke::SoftSelectionSpatialIndex *build_object_selected_index(
      BMesh &bm, const Span<float3> world_positions)
  {
    Vector<float3> selected_positions;
    selected_positions.reserve(bm.totvertsel);
    BMIter iter;
    BMVert *vert;
    BM_ITER_MESH (vert, &iter, &bm, BM_VERTS_OF_MESH) {
      if (selected_visible(*vert)) {
        selected_positions.append(world_positions[BM_elem_index_get(vert)]);
      }
    }
    return bke::soft_selection_spatial_index_create(selected_positions);
  }

  float4 color_from_weight(const float weight) const
  {
    float color[4] = {0.0f, 0.0f, 0.0f, 1.0f};
    BKE_colorband_evaluate(&settings_.falloff_color, weight, color);
    /* Maya's softSelectColorCurve is RGB-only; alpha must not weaken component feedback. */
    return float4(color[0], color[1], color[2], 1.0f);
  }

 public:
  ~SoftSelectionFalseColor()
  {
    free_global_index();
  }

  void begin_sync(Resources &res, const State &state) final
  {
    edges_.clear();
    vertices_.clear();
    free_global_index();
    curve_.reset();

    const ToolSettings *tool_settings = state.scene != nullptr ? state.scene->toolsettings :
                                                                 nullptr;
    enabled_ = state.is_space_v3d() && state.ctx_mode == CTX_MODE_EDIT_MESH &&
               !state.hide_overlays && !state.is_depth_only_drawing && !res.is_selection() &&
               tool_settings != nullptr &&
               (tool_settings->proportional_edit & PROP_EDIT_USE) != 0 &&
               tool_settings->soft_selection.use_falloff_color != 0;
    if (!enabled_) {
      return;
    }

    settings_ = tool_settings->soft_selection;
    if (!std::isfinite(settings_.radius) || settings_.radius <= 0.0f ||
        settings_.falloff_color.tot <= 0)
    {
      enabled_ = false;
      return;
    }
    curve_.emplace(settings_);
    show_vertices_ = (tool_settings->selectmode & SCE_SELECT_VERTEX) != 0;
    xray_flag_enabled_ = state.xray_flag_enabled;

    if (settings_.falloff_mode == SOFT_SELECT_FALLOFF_GLOBAL) {
      build_global_selected_index(state);
      enabled_ = global_selected_index_ != nullptr;
    }
  }

  void edit_object_sync(Manager & /*manager*/,
                        const ObjectRef &ob_ref,
                        Resources & /*res*/,
                        const State & /*state*/) final
  {
    if (!enabled_ || ob_ref.object->type != OB_MESH || !curve_.has_value()) {
      return;
    }

    Object *object_orig = DEG_get_original(ob_ref.object);
    BMEditMesh *edit_mesh = object_orig != nullptr ? BKE_editmesh_from_object(object_orig) :
                                                     nullptr;
    if (edit_mesh == nullptr || edit_mesh->bm == nullptr || edit_mesh->bm->totvert == 0) {
      return;
    }

    BMesh &bm = *edit_mesh->bm;
    const float4x4 object_to_world = ob_ref.object_to_world(0);
    BM_mesh_elem_index_ensure(&bm, BM_VERT);
    Array<float3> world_positions(bm.totvert);
    BMIter position_iter;
    BMVert *position_vert;
    BM_ITER_MESH (position_vert, &position_iter, &bm, BM_VERTS_OF_MESH) {
      if (!BM_elem_flag_test(position_vert, BM_ELEM_HIDDEN)) {
        world_positions[BM_elem_index_get(position_vert)] = math::transform_point(
            object_to_world, float3(position_vert->co));
      }
    }
    Array<float> distances(bm.totvert, FLT_MAX);

    bke::SoftSelectionSpatialIndex *object_index = nullptr;
    if (settings_.falloff_mode == SOFT_SELECT_FALLOFF_SURFACE) {
      if (bm.totvertsel == 0) {
        return;
      }
      float distance_matrix[3][3];
      copy_m3_m4(distance_matrix, object_to_world.ptr());
      bke::soft_selection_mesh_surface_distances(&bm, distance_matrix, distances.data(), nullptr);
    }
    else {
      const bke::SoftSelectionSpatialIndex *spatial_index = global_selected_index_;
      if (settings_.falloff_mode == SOFT_SELECT_FALLOFF_VOLUME) {
        object_index = build_object_selected_index(bm, world_positions);
        spatial_index = object_index;
      }
      if (spatial_index == nullptr) {
        return;
      }

      BMIter iter;
      BMVert *vert;
      BM_ITER_MESH (vert, &iter, &bm, BM_VERTS_OF_MESH) {
        if (BM_elem_flag_test(vert, BM_ELEM_HIDDEN)) {
          continue;
        }
        const int index = BM_elem_index_get(vert);
        if (selected_visible(*vert)) {
          distances[index] = 0.0f;
          continue;
        }
        bke::soft_selection_spatial_index_nearest_distance(
            spatial_index, world_positions[index], distances[index]);
      }
    }

    Array<float4> colors(bm.totvert);
    Array<bool> affected(bm.totvert, false);
    BMIter viter;
    BMVert *vert;
    BM_ITER_MESH (vert, &viter, &bm, BM_VERTS_OF_MESH) {
      const int index = BM_elem_index_get(vert);
      if (BM_elem_flag_test(vert, BM_ELEM_HIDDEN) || distances[index] > settings_.radius) {
        continue;
      }
      affected[index] = true;
      const float weight = bke::soft_selection_weight(
          *curve_, distances[index], settings_.radius, selected_visible(*vert));
      colors[index] = color_from_weight(weight);
      if (show_vertices_) {
        vertices_.append(world_positions[index], colors[index]);
      }
    }

    /* Autodesk explicitly documents colored edges in every component-selection mode. */
    const float4 zero_weight_color = color_from_weight(0.0f);
    BMIter eiter;
    BMEdge *edge;
    BM_ITER_MESH (edge, &eiter, &bm, BM_EDGES_OF_MESH) {
      if (BM_elem_flag_test(edge, BM_ELEM_HIDDEN) || BM_elem_flag_test(edge->v1, BM_ELEM_HIDDEN) ||
          BM_elem_flag_test(edge->v2, BM_ELEM_HIDDEN))
      {
        continue;
      }
      const int index_1 = BM_elem_index_get(edge->v1);
      const int index_2 = BM_elem_index_get(edge->v2);
      if (!affected[index_1] && !affected[index_2]) {
        continue;
      }

      const float4 color_1 = affected[index_1] ? colors[index_1] : zero_weight_color;
      const float4 color_2 = affected[index_2] ? colors[index_2] : zero_weight_color;
      edges_.append(world_positions[index_1], world_positions[index_2], color_1, color_2);
    }

    bke::soft_selection_spatial_index_free(object_index);
  }

  void end_sync(Resources &res, const State &state) final
  {
    free_global_index();
    if (!enabled_) {
      return;
    }

    ps_.init();
    ps_.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
    ps_.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
    const DRWState pass_state = DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_LESS_EQUAL |
                                DRW_STATE_BLEND_ALPHA;
    {
      PassSimple::Sub &sub = ps_.sub("colored_edges");
      sub.state_set(pass_state, state.clipping_plane_count);
      sub.shader_set(res.shaders->soft_selection_wire.get());
      sub.push_constant("ndc_offset_factor", &state.ndc_offset_factor);
      sub.push_constant("ndc_offset", 1.25f);
      edges_.end_sync(sub);
    }
    {
      PassSimple::Sub &sub = ps_.sub("colored_vertices");
      sub.state_set(pass_state, state.clipping_plane_count);
      sub.shader_set(res.shaders->soft_selection_point.get());
      sub.push_constant("ndc_offset_factor", &state.ndc_offset_factor);
      sub.push_constant("ndc_offset", 1.5f);
      vertices_.end_sync(sub);
    }
  }

  void draw_line(Framebuffer &framebuffer, Manager &manager, View &view) final
  {
    if (!enabled_ || xray_flag_enabled_) {
      return;
    }
    GPU_framebuffer_bind(framebuffer);
    manager.submit(ps_, view);
  }

  void draw_color_only(Framebuffer &framebuffer, Manager &manager, View &view) final
  {
    if (!enabled_ || !xray_flag_enabled_) {
      return;
    }
    GPU_framebuffer_bind(framebuffer);
    manager.submit(ps_, view);
  }
};

/**
 * Draw edit mesh overlays.
 */
class Meshes : Overlay {
 private:
  PassSimple edit_mesh_normals_ps_ = {"Normals"};
  PassSimple::Sub *face_normals_ = nullptr;
  PassSimple::Sub *face_normals_subdiv_ = nullptr;
  PassSimple::Sub *loop_normals_ = nullptr;
  PassSimple::Sub *loop_normals_subdiv_ = nullptr;
  PassSimple::Sub *vert_normals_ = nullptr;
  PassSimple::Sub *vert_normals_subdiv_ = nullptr;

  PassSimple edit_mesh_analysis_ps_ = {"Mesh Analysis"};
  PassSimple edit_mesh_weight_ps_ = {"Edit Weight"};

  PassSimple edit_mesh_edges_ps_ = {"Edges"};
  PassSimple edit_mesh_faces_ps_ = {"Faces"};
  PassSimple edit_mesh_cages_ps_ = {"Cages"}; /* Same as faces but with a different offset. */
  PassSimple edit_mesh_verts_ps_ = {"Verts"};
  PassSimple edit_mesh_facedots_ps_ = {"FaceDots"};
  PassSimple edit_mesh_skin_roots_ps_ = {"SkinRoots"};

  /* Depth pre-pass to cull edit cage in case the object is not opaque. */
  PassSimple edit_mesh_prepass_ps_ = {"Prepass"};

  bool xray_enabled_ = false;
  bool xray_flag_enabled_ = false;

  bool show_retopology_ = false;
  bool show_mesh_analysis_ = false;
  bool show_face_overlay_ = false;
  bool show_weight_ = false;

  bool select_vert_ = false;
  bool select_edge_ = false;
  bool select_face_ = false;
  bool select_face_dots_ = false;

  /**
   * Depth offsets applied in screen space to different edit overlay components.
   * This is multiplied by a factor based on zoom level computed by `GPU_polygon_offset_calc`.
   */
  static constexpr float cage_ndc_offset_ = 0.5f;
  static constexpr float edge_ndc_offset_ = 1.0f;
  static constexpr float vert_ndc_offset_ = 1.5f;

  /* TODO(fclem): This is quite wasteful and expensive, prefer in shader Z modification like the
   * retopology offset. */
  View view_edit_cage_ = {"view_edit_cage"};
  View::OffsetData offset_data_;

 public:
  void begin_sync(Resources &res, const State &state) final
  {
    enabled_ = state.is_space_v3d();

    if (!enabled_) {
      return;
    }

    offset_data_ = state.offset_data_get();
    xray_enabled_ = state.xray_enabled;
    xray_flag_enabled_ = state.xray_flag_enabled;

    const int edit_flag = state.v3d->overlay.edit_flag;

    const ToolSettings *tsettings = state.scene->toolsettings;
    select_vert_ = (tsettings->selectmode & SCE_SELECT_VERTEX);
    select_edge_ = (tsettings->selectmode & SCE_SELECT_EDGE);
    select_face_ = (tsettings->selectmode & SCE_SELECT_FACE);
    select_face_dots_ = (edit_flag & V3D_OVERLAY_EDIT_FACE_DOT) ||
                        (state.xray_flag_enabled && select_face_);

    show_retopology_ = (edit_flag & V3D_OVERLAY_EDIT_RETOPOLOGY) && !state.xray_enabled;
    show_mesh_analysis_ = (edit_flag & V3D_OVERLAY_EDIT_STATVIS);
    show_face_overlay_ = (edit_flag & V3D_OVERLAY_EDIT_FACES);
    show_weight_ = (edit_flag & V3D_OVERLAY_EDIT_WEIGHT);

    const bool show_face_nor = (edit_flag & V3D_OVERLAY_EDIT_FACE_NORMALS);
    const bool show_loop_nor = (edit_flag & V3D_OVERLAY_EDIT_LOOP_NORMALS);
    const bool show_vert_nor = (edit_flag & V3D_OVERLAY_EDIT_VERT_NORMALS);

    const bool do_smooth_wire = (U.gpu_flag & USER_GPU_FLAG_NO_EDIT_MODE_SMOOTH_WIRE) == 0;
    const bool is_wire_shading_mode = (state.v3d->shading.type == OB_WIRE);

    uint4 data_mask = data_mask_get(edit_flag);

    float backwire_opacity = (state.xray_flag_enabled) ? 0.5f : 1.0f;
    float face_alpha = (show_face_overlay_) ? 1.0f : 0.0f;
    float retopology_offset = state.is_depth_only_drawing ? 0.0f : RETOPOLOGY_OFFSET(state.v3d);
    /* Cull back-faces for retopology face pass. This makes it so back-faces are not drawn.
     * Doing so lets us distinguish back-faces from front-faces. */
    DRWState face_culling = (show_retopology_) ? DRW_STATE_CULL_BACK : DRWState(0);

    gpu::Texture **depth_tex = (state.xray_flag_enabled) ? &res.depth_tx : &res.dummy_depth_tx;

    {
      auto &pass = edit_mesh_prepass_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_DEPTH | DRW_STATE_DEPTH_LESS_EQUAL | face_culling,
                     state.clipping_plane_count);
      pass.shader_set(res.shaders->mesh_edit_depth.get());
      pass.push_constant("retopology_offset", retopology_offset);
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
    }
    {
      /* Normals */
      const bool use_screen_size = (edit_flag & V3D_OVERLAY_EDIT_CONSTANT_SCREEN_SIZE_NORMALS);
      const bool use_hq_normals = (state.scene->r.perf_flag & SCE_PERF_HQ_NORMALS) ||
                                  GPU_use_hq_normals_workaround();

      DRWState pass_state = DRW_STATE_WRITE_DEPTH | DRW_STATE_WRITE_COLOR |
                            DRW_STATE_DEPTH_LESS_EQUAL;
      if (state.xray_flag_enabled) {
        pass_state |= DRW_STATE_BLEND_ALPHA;
      }

      auto &pass = edit_mesh_normals_ps_;
      pass.init();
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
      pass.state_set(pass_state, state.clipping_plane_count);

      auto shader_pass = [&](gpu::Shader *shader, const char *name) {
        auto &sub = pass.sub(name);
        sub.shader_set(shader);
        sub.bind_texture("depth_tx", depth_tex);
        sub.push_constant("alpha", backwire_opacity);
        sub.push_constant("is_constant_screen_size_normals", use_screen_size);
        sub.push_constant("normal_size", state.overlay.normals_length);
        sub.push_constant("normal_screen_size", state.overlay.normals_constant_screen_size);
        sub.push_constant("retopology_offset", retopology_offset);
        sub.push_constant("hq_normals", use_hq_normals);
        return &sub;
      };

      face_normals_ = loop_normals_ = vert_normals_ = nullptr;

      if (show_face_nor) {
        face_normals_subdiv_ = shader_pass(res.shaders->mesh_face_normal_subdiv.get(), "SubdFNor");
        face_normals_ = shader_pass(res.shaders->mesh_face_normal.get(), "FaceNor");
      }
      if (show_loop_nor) {
        loop_normals_subdiv_ = shader_pass(res.shaders->mesh_loop_normal_subdiv.get(), "SubdLNor");
        loop_normals_ = shader_pass(res.shaders->mesh_loop_normal.get(), "LoopNor");
      }
      if (show_vert_nor) {
        vert_normals_subdiv_ = shader_pass(res.shaders->mesh_vert_normal_subdiv.get(), "SubdVNor");
        vert_normals_ = shader_pass(res.shaders->mesh_vert_normal.get(), "VertexNor");
      }
    }
    {
      /* Support masked transparency in Workbench.
       * EEVEE can't be supported since depth won't match. */
      const bool shadeless = eDrawType(state.v3d->shading.type) == OB_WIRE;

      auto &pass = edit_mesh_weight_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_LESS_EQUAL | DRW_STATE_WRITE_DEPTH,
                     state.clipping_plane_count);
      pass.shader_set(shadeless ? res.shaders->paint_weight.get() :
                                  res.shaders->paint_weight_fake_shading.get());
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
      pass.bind_texture("colorramp", &res.weight_ramp_tx);
      pass.push_constant("draw_contours", false);
      pass.push_constant("opacity", state.overlay.weight_paint_mode_opacity);
      if (!shadeless) {
        /* Arbitrary light to give a hint of the geometry behind the weights. */
        pass.push_constant("light_dir", math::normalize(float3(0.0f, 0.5f, 0.86602f)));
      }
    }
    {
      auto &pass = edit_mesh_analysis_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_LESS_EQUAL | DRW_STATE_BLEND_ALPHA,
                     state.clipping_plane_count);
      pass.shader_set(res.shaders->mesh_analysis.get());
      pass.bind_texture("weight_tx", res.weight_ramp_tx);
    }

    auto mesh_edit_common_resource_bind = [&](PassSimple &pass, float alpha, float ndc_offset) {
      pass.bind_texture("depth_tx", depth_tex);
      /* TODO(fclem): UBO. */
      pass.push_constant("wire_shading", is_wire_shading_mode);
      pass.push_constant("select_vert", select_vert_);
      pass.push_constant("select_face", select_face_);
      pass.push_constant("select_edge", select_edge_);
      pass.push_constant("alpha", alpha);
      pass.push_constant("retopology_offset", retopology_offset);
      pass.push_constant("ndc_offset_factor", &state.ndc_offset_factor);
      pass.push_constant("ndc_offset", ndc_offset);
      pass.push_constant("data_mask", int4(data_mask));
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
    };

    {
      auto &pass = edit_mesh_edges_ps_;
      pass.init();
      /* Change first vertex convention to match blender loop structure. */
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_LESS_EQUAL | DRW_STATE_BLEND_ALPHA |
                         DRW_STATE_FIRST_VERTEX_CONVENTION,
                     state.clipping_plane_count);
      pass.shader_set(res.shaders->mesh_edit_edge.get());
      pass.push_constant("do_smooth_wire", do_smooth_wire);
      pass.push_constant("use_vertex_selection", select_vert_);
      mesh_edit_common_resource_bind(pass, backwire_opacity, edge_ndc_offset_);
    }
    {
      auto &pass = edit_mesh_faces_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_LESS_EQUAL | DRW_STATE_BLEND_ALPHA |
                         face_culling,
                     state.clipping_plane_count);
      pass.shader_set(res.shaders->mesh_edit_face.get());
      mesh_edit_common_resource_bind(pass, face_alpha, 0.0f);
    }
    {
      auto &pass = edit_mesh_cages_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_LESS_EQUAL | DRW_STATE_BLEND_ALPHA,
                     state.clipping_plane_count);
      pass.shader_set(res.shaders->mesh_edit_face.get());
      mesh_edit_common_resource_bind(pass, face_alpha, cage_ndc_offset_);
    }
    {
      auto &pass = edit_mesh_verts_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_LESS_EQUAL | DRW_STATE_BLEND_ALPHA |
                         DRW_STATE_WRITE_DEPTH,
                     state.clipping_plane_count);
      pass.shader_set(res.shaders->mesh_edit_vert.get());
      mesh_edit_common_resource_bind(pass, backwire_opacity, vert_ndc_offset_);
    }
    {
      auto &pass = edit_mesh_facedots_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_LESS_EQUAL | DRW_STATE_BLEND_ALPHA |
                         DRW_STATE_WRITE_DEPTH,
                     state.clipping_plane_count);
      pass.shader_set(res.shaders->mesh_edit_facedot.get());
      mesh_edit_common_resource_bind(pass, backwire_opacity, vert_ndc_offset_);
    }
    {
      auto &pass = edit_mesh_skin_roots_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_LESS_EQUAL | DRW_STATE_BLEND_ALPHA |
                         DRW_STATE_WRITE_DEPTH,
                     state.clipping_plane_count);
      pass.shader_set(res.shaders->mesh_edit_skin_root.get());
      pass.push_constant("retopology_offset", retopology_offset);
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
    }
  }

  void edit_object_sync(Manager &manager,
                        const ObjectRef &ob_ref,
                        Resources & /*res*/,
                        const State &state) final
  {
    if (!enabled_) {
      return;
    }

    ResourceHandleRange res_handle = manager.unique_handle(ob_ref);

    Object *ob = ob_ref.object;
    Mesh &mesh = DRW_object_get_data_for_drawing<Mesh>(*ob);
    /* WORKAROUND: GPU subdiv uses a different normal format. Remove this once GPU subdiv is
     * refactored. */
    const bool use_gpu_subdiv = BKE_subsurf_modifier_has_gpu_subdiv(&mesh);
    const bool draw_as_solid = (ob->dt > OB_WIRE) && !state.xray_enabled;
    const bool has_edit_cage = mesh_has_edit_cage(ob);

    if (show_retopology_) {
      gpu::Batch *geom = DRW_mesh_batch_cache_get_edit_triangles(mesh);
      edit_mesh_prepass_ps_.draw(geom, res_handle);
    }
    if (draw_as_solid && !state.is_render_depth_available) {
      gpu::Batch *geom = DRW_cache_mesh_surface_get(ob);
      edit_mesh_prepass_ps_.draw(geom, res_handle);
    }

    if (show_mesh_analysis_) {
      gpu::Batch *geom = DRW_cache_mesh_surface_mesh_analysis_get(ob);
      edit_mesh_analysis_ps_.draw(geom, res_handle);
    }

    if (show_weight_) {
      gpu::Batch *geom = DRW_cache_mesh_surface_weights_get(ob);
      edit_mesh_weight_ps_.draw(geom, res_handle);
    }

    if (face_normals_) {
      gpu::Batch *geom = DRW_mesh_batch_cache_get_edit_facedots(mesh);
      (use_gpu_subdiv && !has_edit_cage ? face_normals_subdiv_ : face_normals_)
          ->draw_expand(geom, GPU_PRIM_LINES, 1, 1, res_handle);
    }
    if (loop_normals_) {
      gpu::Batch *geom = DRW_mesh_batch_cache_get_edit_loop_normals(mesh);
      (use_gpu_subdiv && !has_edit_cage ? loop_normals_subdiv_ : loop_normals_)
          ->draw_expand(geom, GPU_PRIM_LINES, 1, 1, res_handle);
    }
    if (vert_normals_) {
      gpu::Batch *geom = DRW_mesh_batch_cache_get_edit_vert_normals(mesh);
      ((use_gpu_subdiv && !has_edit_cage) ? vert_normals_subdiv_ : vert_normals_)
          ->draw_expand(geom, GPU_PRIM_LINES, 1, 1, res_handle);
    }

    {
      gpu::Batch *geom = DRW_mesh_batch_cache_get_edit_edges(mesh);
      edit_mesh_edges_ps_.draw_expand(geom, GPU_PRIM_TRIS, 2, 1, res_handle);
    }
    {
      gpu::Batch *geom = DRW_mesh_batch_cache_get_edit_triangles(mesh);
      (has_edit_cage ? &edit_mesh_cages_ps_ : &edit_mesh_faces_ps_)->draw(geom, res_handle);
    }
    if (select_vert_) {
      gpu::Batch *geom = DRW_mesh_batch_cache_get_edit_vertices(mesh);
      edit_mesh_verts_ps_.draw(geom, res_handle);
    }
    if (select_face_dots_) {
      gpu::Batch *geom = DRW_mesh_batch_cache_get_edit_facedots(mesh);
      edit_mesh_facedots_ps_.draw(geom, res_handle);
    }

    if (mesh_has_skin_roots(ob)) {
      gpu::Batch *geom = DRW_mesh_batch_cache_get_edit_skin_roots(mesh);
      edit_mesh_skin_roots_ps_.draw_expand(geom, GPU_PRIM_LINES, 15, 1, res_handle);
    }
    if (state.show_text && (state.overlay.edit_flag & overlay_edit_text)) {
      DRW_text_edit_mesh_measure_stats(state.region, state.v3d, ob, state.scene->unit, state.dt);
    }
  }

  void draw_line(Framebuffer &framebuffer, Manager &manager, View &view) final
  {
    if (!enabled_) {
      return;
    }

    GPU_debug_group_begin("Mesh Edit");

    GPU_framebuffer_bind(framebuffer);
    manager.submit(edit_mesh_prepass_ps_, view);
    manager.submit(edit_mesh_analysis_ps_, view);
    manager.submit(edit_mesh_weight_ps_, view);

    if (!xray_enabled_) {
      /* Still use depth-testing for selected faces when X-Ray flag is enabled but transparency is
       * off (X-Ray Opacity == 1.0 or in Preview/Render mode) (See #135325). */
      manager.submit(edit_mesh_faces_ps_, view);
      manager.submit(edit_mesh_cages_ps_, view);
    }

    if (xray_flag_enabled_) {
      GPU_debug_group_end();
      return;
    }

    manager.submit(edit_mesh_normals_ps_, view);
    manager.submit(edit_mesh_edges_ps_, view);
    manager.submit(edit_mesh_verts_ps_, view);
    manager.submit(edit_mesh_skin_roots_ps_, view);
    manager.submit(edit_mesh_facedots_ps_, view);

    GPU_debug_group_end();
  }

  void draw_color_only(Framebuffer &framebuffer, Manager &manager, View &view) final
  {
    if (!enabled_) {
      return;
    }

    if (xray_enabled_) {
      /* Still use depth-testing for selected faces when X-Ray flag is enabled but transparency is
       * off (X-Ray Opacity == 1.0 or in Preview/Render mode) (See #135325). */
      GPU_framebuffer_bind(framebuffer);
      manager.submit(edit_mesh_faces_ps_, view);
      manager.submit(edit_mesh_cages_ps_, view);
    }

    if (!xray_flag_enabled_) {
      return;
    }

    GPU_debug_group_begin("Mesh Edit Color Only");

    GPU_framebuffer_bind(framebuffer);
    manager.submit(edit_mesh_normals_ps_, view);
    manager.submit(edit_mesh_edges_ps_, view);
    manager.submit(edit_mesh_verts_ps_, view);
    manager.submit(edit_mesh_skin_roots_ps_, view);
    manager.submit(edit_mesh_facedots_ps_, view);

    GPU_debug_group_end();
  }

  static bool mesh_has_edit_cage(const Object *ob)
  {
    BLI_assert(ob->type == OB_MESH);
    Mesh &mesh = DRW_object_get_data_for_drawing<Mesh>(*ob);
    if (mesh.runtime->edit_mesh != nullptr) {
      const Mesh *editmesh_eval_final = BKE_object_get_editmesh_eval_final(ob);
      const Mesh *editmesh_eval_cage = BKE_object_get_editmesh_eval_cage(ob);

      return (editmesh_eval_cage != nullptr) && (editmesh_eval_cage != editmesh_eval_final);
    }
    return false;
  }

 private:
  uint4 data_mask_get(const int flag)
  {
    uint4 mask = {0xFF, 0xFF, 0x00, 0x00};
    SET_FLAG_FROM_TEST(mask[0], flag & V3D_OVERLAY_EDIT_FACES, VFLAG_FACE_SELECTED);
    SET_FLAG_FROM_TEST(mask[0], flag & V3D_OVERLAY_EDIT_FREESTYLE_FACE, VFLAG_FACE_FREESTYLE);
    SET_FLAG_FROM_TEST(mask[1], flag & V3D_OVERLAY_EDIT_FREESTYLE_EDGE, VFLAG_EDGE_FREESTYLE);
    SET_FLAG_FROM_TEST(mask[1], flag & V3D_OVERLAY_EDIT_SEAMS, VFLAG_EDGE_SEAM);
    SET_FLAG_FROM_TEST(mask[1], flag & V3D_OVERLAY_EDIT_SHARP, VFLAG_EDGE_SHARP);
    SET_FLAG_FROM_TEST(mask[2], flag & V3D_OVERLAY_EDIT_CREASES, 0xFF);
    SET_FLAG_FROM_TEST(mask[3], flag & V3D_OVERLAY_EDIT_BWEIGHTS, 0xFF);
    return mask;
  }

  static bool mesh_has_skin_roots(const Object *ob)
  {
    Mesh &mesh = DRW_object_get_data_for_drawing<Mesh>(*ob);
    if (BMEditMesh *em = mesh.runtime->edit_mesh.get()) {
      return CustomData_get_offset(&em->bm->vdata, CD_MVERT_SKIN) != -1;
    }
    return false;
  }
};

/**
 * Draw edit uv overlays.
 */
class MeshUVs : Overlay {
 private:
  PassSimple analysis_ps_ = {"Mesh Analysis"};

  /* TODO(fclem): Should be its own Overlay?. */
  PassSimple wireframe_ps_ = {"Wireframe"};

  PassSimple edges_ps_ = {"Edges"};
  PassSimple faces_ps_ = {"Faces"};
  PassSimple verts_ps_ = {"Verts"};
  PassSimple facedots_ps_ = {"FaceDots"};

  /* TODO(fclem): Should be its own Overlay?. */
  PassSimple image_border_ps_ = {"ImageBorder"};

  /* TODO(fclem): Should be its own Overlay?. */
  PassSimple brush_stencil_ps_ = {"BrushStencil"};

  /* TODO(fclem): Should be its own Overlay?. */
  PassSimple paint_mask_ps_ = {"PaintMask"};

  bool select_vert_ = false;
  bool select_edge_ = false;
  bool select_face_ = false;
  bool select_face_dots_ = false;

  bool show_face_overlay_ = false;

  bool show_uv_edit_ = false;

  /** Wireframe Overlay */
  /* Draw final evaluated UVs (modifier stack applied) as grayed out wire-frame. */
  /* TODO(fclem): Maybe should be its own Overlay?. */
  bool show_wireframe_ = false;

  /** Brush stencil. */
  /* TODO(fclem): Maybe should be its own Overlay?. */
  bool show_stencil_ = false;

  /** Paint Mask overlay. */
  /* TODO(fclem): Maybe should be its own Overlay?. */
  bool show_mask_ = false;
  MaskOverlayMode mask_mode_ = MASK_OVERLAY_ALPHACHANNEL;
  Mask *mask_id_ = nullptr;
  Texture mask_texture_ = {"mask_texture_"};

  /** Stretching Overlay. */
  bool show_mesh_analysis_ = false;
  eSpaceImage_UVDT_Stretch mesh_analysis_type_;
  /**
   * In order to display the stretching relative to all objects in edit mode, we have to sum the
   * area ***AFTER*** extraction and before drawing. To that end, we get a pointer to the resulting
   * total per mesh area location to dereference after extraction.
   */
  Vector<float *> per_mesh_area_3d_;
  Vector<float *> per_mesh_area_2d_;
  float total_area_ratio_;

  /** UDIM border overlay. */
  bool show_tiled_image_active_ = false;
  bool show_tiled_image_border_ = false;
  bool show_tiled_image_label_ = false;

 public:
  void begin_sync(Resources &res, const State &state) final
  {
    enabled_ = state.is_space_image();

    if (!enabled_) {
      return;
    }

    const ToolSettings *tool_setting = state.scene->toolsettings;
    const SpaceImage *space_image = reinterpret_cast<const SpaceImage *>(state.space_data);
    blender::Image *image = space_image->image;
    const bool space_mode_is_paint = space_image->mode == SI_MODE_PAINT;
    const bool space_mode_is_mask = space_image->mode == SI_MODE_MASK;
    const bool space_mode_is_uv = space_image->mode == SI_MODE_UV;

    const bool object_mode_is_edit = state.object_mode & OB_MODE_EDIT;

    const bool is_viewer = image && ELEM(image->type, IMA_TYPE_R_RESULT, IMA_TYPE_COMPOSITE);
    const bool is_tiled_image = image && (image->source == IMA_SRC_TILED);

    /* The mask overlay is always drawn when enabled, even on top of viewers. */
    {
      /* Mask Overlay. */
      show_mask_ = space_mode_is_mask && space_image->mask_info.mask &&
                   space_image->mask_info.draw_flag & MASK_DRAWFLAG_OVERLAY;
      if (show_mask_) {
        mask_mode_ = MaskOverlayMode(space_image->mask_info.overlay_mode);
        mask_id_ = DEG_get_evaluated(state.depsgraph, space_image->mask_info.mask);
      }
      else {
        mask_id_ = nullptr;
      }
    }

    /* Only disable UV drawing on top of render results.
     * Otherwise, show UVs even in the absence of active image. */
    enabled_ = !is_viewer || show_mask_;

    if (!enabled_) {
      return;
    }

    {
      /* Edit UV Overlay. */
      show_uv_edit_ = space_mode_is_uv && object_mode_is_edit;
      show_mesh_analysis_ = show_uv_edit_ && (space_image->flag & SI_DRAW_STRETCH);

      if (!show_uv_edit_) {
        select_vert_ = false;
        select_edge_ = false;
        select_face_ = false;
        select_face_dots_ = false;

        show_face_overlay_ = false;
      }
      else {
        const bool hide_faces = space_image->flag & SI_NO_DRAWFACES;
        select_face_ = !show_mesh_analysis_ && !hide_faces;

        /* FIXME: Always showing verts in edge mode when `uv_select_sync_valid`.
         * needs investigation. */
        if (tool_setting->uv_flag & UV_FLAG_SELECT_SYNC) {
          const char sel_mode_3d = tool_setting->selectmode;
          if (tool_setting->uv_sticky == UV_STICKY_VERT) {
            /* NOTE: Ignore #SCE_SELECT_VERTEX because a single selected edge
             * on the mesh may cause single UV vertices to be selected. */
            select_vert_ = true;
          }
          else {
            select_vert_ = (sel_mode_3d & SCE_SELECT_VERTEX);
          }
          /* When */
          select_edge_ = (sel_mode_3d & SCE_SELECT_VERTEX) == 0;
          select_face_dots_ = (sel_mode_3d & SCE_SELECT_FACE) && !hide_faces;
        }
        else {
          const char sel_mode_2d = tool_setting->uv_selectmode;
          select_vert_ = (sel_mode_2d != UV_SELECT_EDGE);
          select_edge_ = (sel_mode_2d == UV_SELECT_EDGE);
          select_face_dots_ = (sel_mode_2d & UV_SELECT_FACE) && !hide_faces;
        }
      }

      if (show_mesh_analysis_) {
        mesh_analysis_type_ = eSpaceImage_UVDT_Stretch(space_image->dt_uvstretch);
      }
    }
    {
      /* Wireframe UV Overlay. */
      const bool show_wireframe_uv_edit = space_image->flag & SI_DRAWSHADOW;
      const bool show_wireframe_uv_guide = !(space_image->flag & SI_NO_DRAW_UV_GUIDE) &&
                                           (space_mode_is_paint || space_mode_is_uv);

      if (space_mode_is_uv && object_mode_is_edit) {
        show_wireframe_ = show_wireframe_uv_edit;
        show_face_overlay_ = !(space_image->flag & SI_NO_DRAWFACES);
      }
      else {
        show_wireframe_ = show_wireframe_uv_guide;
        /* The face overlay is always enabled when showing wire-frame. */
        show_face_overlay_ = show_wireframe_;
      }
    }

    {
      /* Brush Stencil Overlay. */
      const ImagePaintSettings &image_paint_settings = tool_setting->imapaint;
      const Brush *brush = BKE_paint_brush_for_read(&image_paint_settings.paint);
      show_stencil_ = space_mode_is_paint && brush &&
                      (brush->image_brush_type == IMAGE_PAINT_BRUSH_TYPE_CLONE) &&
                      image_paint_settings.clone;
    }
    {
      /* UDIM Overlay. */
      /* TODO: Always enable this overlay even if overlays are disabled. */
      show_tiled_image_border_ = is_tiled_image;
      show_tiled_image_active_ = is_tiled_image; /* TODO: Only disable this if overlays are off. */
      show_tiled_image_label_ = is_tiled_image;  /* TODO: Only disable this if overlays are off. */
    }

    const bool do_smooth_wire = (U.gpu_flag & USER_GPU_FLAG_OVERLAY_SMOOTH_WIRE) != 0;
    const float dash_length = 4.0f * UI_SCALE_FAC;

    if (show_wireframe_) {
      auto &pass = wireframe_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_WRITE_DEPTH | DRW_STATE_DEPTH_LESS_EQUAL |
                     DRW_STATE_BLEND_ALPHA);
      pass.shader_set(res.shaders->uv_wireframe.get());
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
      pass.push_constant("alpha", space_image->uv_edge_opacity);
      pass.push_constant("do_smooth_wire", do_smooth_wire);
    }

    if (show_uv_edit_) {
      auto &pass = edges_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_WRITE_DEPTH | DRW_STATE_DEPTH_LESS_EQUAL |
                     DRW_STATE_BLEND_ALPHA);

      gpu::Shader *sh = res.shaders->uv_edit_edge.get();
      pass.specialize_constant(sh, "use_edge_select", select_edge_);
      pass.shader_set(sh);
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
      pass.push_constant("line_style", int(edit_uv_line_style_from_space_image(space_image)));

      /* The `uv_opacity` setting does not apply to vertices & face-dots.
       * This means it may be useful show vertices/faces while hiding the wire-frame.
       * An exception to this is when only UV edges are displayed (UV edge mode).
       * In this case, hiding the wire-frame has the effect of hiding UV's entirely.
       * Set the alpha to 1.0 in this case.
       * To hide all UV's, overlays can be disabled entirely. */
      const float alpha = (select_vert_ || select_face_dots_) ? space_image->uv_opacity : 1.0f;
      pass.push_constant("alpha", alpha);
      pass.push_constant("dash_length", dash_length);
      pass.push_constant("do_smooth_wire", do_smooth_wire);
    }

    if (select_vert_) {
      const float dot_size = ui::theme::get_value_f(TH_VERTEX_SIZE) * UI_SCALE_FAC;
      float4 theme_color;
      ui::theme::get_color_4fv(TH_VERTEX, theme_color);
      srgb_to_linearrgb_v4(theme_color, theme_color);

      auto &pass = verts_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_WRITE_DEPTH | DRW_STATE_DEPTH_LESS_EQUAL |
                     DRW_STATE_BLEND_ALPHA);
      pass.shader_set(res.shaders->uv_edit_vert.get());
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
      pass.push_constant("dot_size", (dot_size + 1.5f) * float(M_SQRT2));
      pass.push_constant("outline_width", 0.75f);
      pass.push_constant("color", theme_color);
    }

    if (select_face_dots_) {
      const float dot_size = ui::theme::get_value_f(TH_FACEDOT_SIZE) * UI_SCALE_FAC;

      auto &pass = facedots_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_WRITE_DEPTH | DRW_STATE_DEPTH_LESS_EQUAL |
                     DRW_STATE_BLEND_ALPHA);
      pass.shader_set(res.shaders->uv_edit_facedot.get());
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
      pass.push_constant("dot_size", dot_size);
    }

    if (show_face_overlay_ || select_face_) {
      const float opacity = (object_mode_is_edit && space_mode_is_uv) ?
                                space_image->uv_opacity :
                                space_image->uv_face_opacity;

      auto &pass = faces_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_ALWAYS | DRW_STATE_BLEND_ALPHA);
      pass.shader_set(res.shaders->uv_edit_face.get());
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
      pass.push_constant("uv_opacity", opacity);
    }

    if (show_mesh_analysis_) {
      auto &pass = analysis_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_ALWAYS | DRW_STATE_BLEND_ALPHA);
      pass.shader_set(mesh_analysis_type_ == SI_UVDT_STRETCH_ANGLE ?
                          res.shaders->uv_analysis_stretch_angle.get() :
                          res.shaders->uv_analysis_stretch_area.get());
      pass.bind_ubo(OVERLAY_GLOBALS_SLOT, &res.globals_buf);
      pass.bind_ubo(DRW_CLIPPING_UBO_SLOT, &res.clip_planes_buf);
      pass.push_constant("aspect", state.image_uv_aspect);
      pass.push_constant("stretch_opacity", space_image->stretch_opacity);
      pass.push_constant("total_area_ratio", &total_area_ratio_);
    }

    per_mesh_area_3d_.clear();
    per_mesh_area_2d_.clear();
  }

  void object_sync(Manager &manager,
                   const ObjectRef &ob_ref,
                   Resources & /*res*/,
                   const State &state) final
  {
    if (!enabled_ || ob_ref.object->type != OB_MESH ||
        !((ob_ref.object->base_flag & BASE_SELECTED) || (ob_ref.object == state.object_active)))
    {
      return;
    }

    Object *ob = ob_ref.object;
    Mesh &mesh = DRW_object_get_data_for_drawing<Mesh>(*ob);

    const SpaceImage *space_image = reinterpret_cast<const SpaceImage *>(state.space_data);
    const StringRef active_uv_map = mesh.active_or_default_uv_map_name();
    const bke::AttributeAccessor attributes = mesh.attributes();
    const std::optional<bke::AttributeMetaData> meta_data = attributes.lookup_meta_data(
        active_uv_map);
    const bool has_active_object_uvmap = bke::mesh::is_uv_map(meta_data);

    ResourceHandleRange res_handle = manager.unique_handle(ob_ref);

    if (show_wireframe_ && has_active_object_uvmap) {
      gpu::Batch *geom = DRW_mesh_batch_cache_get_all_uv_wireframe(*ob, mesh);
      wireframe_ps_.draw_expand(geom, GPU_PRIM_TRIS, 2, 1, res_handle);
    }
    if (show_face_overlay_ && has_active_object_uvmap && space_image->uv_face_opacity > 0.0f) {
      gpu::Batch *geom = DRW_mesh_batch_cache_get_uv_faces(*ob, mesh);
      faces_ps_.draw(geom, res_handle);
    }
  }

  void edit_object_sync(Manager &manager,
                        const ObjectRef &ob_ref,
                        Resources & /*res*/,
                        const State &state) final
  {
    if (!enabled_ || ob_ref.object->type != OB_MESH) {
      return;
    }

    Object &ob = *ob_ref.object;
    Mesh &mesh = DRW_object_get_data_for_drawing<Mesh>(ob);

    const Object *ob_orig = DEG_get_original(ob_ref.object);
    const Mesh &mesh_orig = ob_orig->type == OB_MESH ? *id_cast<Mesh *>(ob_orig->data) : mesh;

    const SpaceImage *space_image = reinterpret_cast<const SpaceImage *>(state.space_data);
    const bool is_edit_object = DRW_object_is_in_edit_mode(&ob);
    const bool is_uv_editable = is_edit_object && space_image->mode == SI_MODE_UV;
    /* Sculpt is left out here because selection does not exist in it. */
    const bool is_paint_mode = ELEM(
        state.ctx_mode, CTX_MODE_PAINT_TEXTURE, CTX_MODE_PAINT_VERTEX, CTX_MODE_PAINT_WEIGHT);
    const bool use_face_selection = (mesh_orig.editflag & ME_EDIT_PAINT_FACE_SEL);
    const bool is_face_selectable = (is_edit_object || (is_paint_mode && use_face_selection));
    const StringRef active_uv_map = mesh.active_or_default_uv_map_name();
    const bke::AttributeAccessor attributes = mesh.attributes();
    const std::optional<bke::AttributeMetaData> meta_data = attributes.lookup_meta_data(
        active_uv_map);
    const bool has_active_object_uvmap = bke::mesh::is_uv_map(meta_data);

    const bool has_active_edit_uvmap = is_edit_object && CustomData_has_layer_named(
                                                             &mesh.runtime->edit_mesh->bm->ldata,
                                                             CD_PROP_FLOAT2,
                                                             active_uv_map);

    ResourceHandleRange res_handle = manager.unique_handle(ob_ref);

    /* Fully editable UVs in the UV Editor. */
    if (has_active_edit_uvmap && is_uv_editable) {
      if (show_uv_edit_) {
        gpu::Batch *geom = DRW_mesh_batch_cache_get_edituv_edges(ob, mesh);
        edges_ps_.draw_expand(geom, GPU_PRIM_TRIS, 2, 1, res_handle);
      }
      if (select_vert_) {
        gpu::Batch *geom = DRW_mesh_batch_cache_get_edituv_verts(ob, mesh);
        verts_ps_.draw(geom, res_handle);
      }
      if (select_face_dots_) {
        gpu::Batch *geom = DRW_mesh_batch_cache_get_edituv_facedots(ob, mesh);
        facedots_ps_.draw(geom, res_handle);
      }
      if (show_face_overlay_ || select_face_) {
        gpu::Batch *geom = DRW_mesh_batch_cache_get_edituv_faces(ob, mesh);
        faces_ps_.draw(geom, res_handle);
      }
      if (show_wireframe_) {
        gpu::Batch *geom = DRW_mesh_batch_cache_get_edituv_wireframe(ob, mesh);
        wireframe_ps_.draw_expand(geom, GPU_PRIM_TRIS, 2, 1, res_handle);
      }

      if (show_mesh_analysis_) {
        int index_3d, index_2d;
        if (mesh_analysis_type_ == SI_UVDT_STRETCH_AREA) {
          index_3d = per_mesh_area_3d_.append_and_get_index(nullptr);
          index_2d = per_mesh_area_2d_.append_and_get_index(nullptr);
        }

        gpu::Batch *geom =
            mesh_analysis_type_ == SI_UVDT_STRETCH_ANGLE ?
                DRW_mesh_batch_cache_get_edituv_faces_stretch_angle(ob, mesh) :
                DRW_mesh_batch_cache_get_edituv_faces_stretch_area(
                    ob, mesh, &per_mesh_area_3d_[index_3d], &per_mesh_area_2d_[index_2d]);

        analysis_ps_.draw(geom, res_handle);
      }
      return;
    }

    /* Selectable faces in 3D viewport that sync with image editor paint mode. */
    if ((has_active_object_uvmap || has_active_edit_uvmap) && is_face_selectable) {
      if (show_wireframe_) {
        gpu::Batch *geom = DRW_mesh_batch_cache_get_uv_wireframe(ob, mesh);
        wireframe_ps_.draw_expand(geom, GPU_PRIM_TRIS, 2, 1, res_handle);
      }
      if ((show_face_overlay_ && space_image->uv_face_opacity > 0.0f) || select_face_) {
        gpu::Batch *geom = DRW_mesh_batch_cache_get_uv_faces(ob, mesh);
        faces_ps_.draw(geom, res_handle);
      }
      return;
    }

    /* Non-selectable & non-editable faces in image editor paint mode. */
    if ((has_active_object_uvmap || has_active_edit_uvmap) && !is_uv_editable &&
        !is_face_selectable)
    {
      if (show_wireframe_) {
        gpu::Batch *geom = DRW_mesh_batch_cache_get_all_uv_wireframe(ob, mesh);
        wireframe_ps_.draw_expand(geom, GPU_PRIM_TRIS, 2, 1, res_handle);
      }
      if (show_face_overlay_ && space_image->uv_face_opacity > 0.0f) {
        gpu::Batch *geom = DRW_mesh_batch_cache_get_uv_faces(ob, mesh);
        faces_ps_.draw(geom, res_handle);
      }
    }
  }

  void end_sync(Resources &res, const State &state) final
  {
    if (!enabled_) {
      return;
    }

    {
      float total_3d = 0.0f;
      float total_2d = 0.0f;
      for (const float *mesh_area_2d : per_mesh_area_2d_) {
        total_2d += *mesh_area_2d;
      }
      for (const float *mesh_area_3d : per_mesh_area_3d_) {
        total_3d += *mesh_area_3d;
      }
      total_area_ratio_ = total_3d * math::safe_rcp(total_2d);
    }

    const ToolSettings *tool_setting = state.scene->toolsettings;
    const SpaceImage *space_image = reinterpret_cast<const SpaceImage *>(state.space_data);
    blender::Image *image = space_image->image;

    if (show_tiled_image_border_) {
      float4 theme_color;
      float4 selected_color;
      uchar4 text_color;
      /* Color Management: Exception here as texts are drawn in sRGB space directly. No conversion
       * required. */
      ui::theme::get_color_shade_4ubv(TH_BACK, 60, text_color);
      ui::theme::get_color_shade_4fv(TH_BACK, 60, theme_color);
      ui::theme::get_color_4fv(TH_FACE_SELECT, selected_color);
      srgb_to_linearrgb_v4(theme_color, theme_color);
      srgb_to_linearrgb_v4(selected_color, selected_color);

      auto &pass = image_border_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_ALWAYS);
      pass.shader_set(res.shaders->uv_image_borders.get());

      auto draw_tile = [&](const ImageTile *tile, const bool is_active) {
        const int tile_x = ((tile->tile_number - 1001) % 10);
        const int tile_y = ((tile->tile_number - 1001) / 10);
        const float3 tile_location(tile_x, tile_y, 0.0f);
        pass.push_constant("tile_pos", tile_location);
        pass.push_constant("ucolor", is_active ? selected_color : theme_color);
        pass.draw(res.shapes.quad_wire.get());

        /* Note: don't draw label twice for active tile. */
        if (show_tiled_image_label_ && !is_active) {
          std::string text = std::to_string(tile->tile_number);
          DRW_text_cache_add(state.dt,
                             tile_location,
                             text.c_str(),
                             text.size(),
                             10,
                             10,
                             DRW_TEXT_CACHE_GLOBALSPACE,
                             text_color);
        }
      };

      ListBaseWrapper<ImageTile> tiles(image->tiles);
      /* image->active_tile_index could point to a non existing ImageTile. To work around this we
       * get the active tile when looping over all tiles. */
      const ImageTile *active_tile = nullptr;
      int tile_index = 0;
      for (const ImageTile *tile : tiles) {
        draw_tile(tile, false);
        if (tile_index == image->active_tile_index) {
          active_tile = tile;
        }
        tile_index++;
      }
      /* Draw active tile on top. */
      if (show_tiled_image_active_ && active_tile != nullptr) {
        draw_tile(active_tile, true);
      }
    }

    if (show_stencil_) {
      auto &pass = brush_stencil_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_ALWAYS |
                     DRW_STATE_BLEND_ALPHA_PREMUL);

      const ImagePaintSettings &image_paint_settings = tool_setting->imapaint;
      blender::Image *stencil_image = image_paint_settings.clone;
      TextureRef stencil_texture;
      stencil_texture.wrap(BKE_image_get_gpu_texture(stencil_image, nullptr));

      if (stencil_texture.is_valid()) {
        float2 size_image;
        BKE_image_get_size_fl(image, nullptr, &size_image[0]);

        pass.shader_set(res.shaders->uv_brush_stencil.get());
        pass.bind_texture("img_tx", stencil_texture);
        pass.push_constant("img_premultiplied", true);
        pass.push_constant("img_alpha_blend", true);
        pass.push_constant("ucolor", float4(1.0f, 1.0f, 1.0f, image_paint_settings.clone_alpha));
        pass.push_constant("brush_offset", float2(image_paint_settings.clone_offset));
        pass.push_constant("brush_scale", float2(stencil_texture.size().xy()) / size_image);
        pass.draw(res.shapes.quad_solid.get());
      }
    }

    if (show_mask_) {
      paint_mask_texture_ensure(mask_id_, state.image_size, state.image_aspect);

      const bool is_combined = mask_mode_ == MASK_OVERLAY_COMBINED;
      const float opacity = is_combined ? space_image->mask_info.blend_factor : 1.0f;

      auto &pass = paint_mask_ps_;
      pass.init();
      pass.state_set(DRW_STATE_WRITE_COLOR | DRW_STATE_DEPTH_ALWAYS |
                     (is_combined ? DRW_STATE_BLEND_MUL : DRW_STATE_BLEND_ALPHA));
      pass.shader_set(res.shaders->uv_paint_mask.get());
      pass.bind_texture("img_tx", mask_texture_);
      pass.push_constant("color", float4(1.0f, 1.0f, 1.0f, 1.0f));
      pass.push_constant("opacity", opacity);
      pass.push_constant("brush_offset", float2(0.0f));
      pass.push_constant("brush_scale", float2(1.0f));
      pass.draw(res.shapes.quad_solid.get());
    }
  }

  void draw(Framebuffer &framebuffer, Manager &manager, View &view) final
  {
    if (!enabled_) {
      return;
    }

    GPU_debug_group_begin("Mesh Edit UVs");

    GPU_framebuffer_bind(framebuffer);
    if (show_mask_ && (mask_mode_ != MASK_OVERLAY_COMBINED)) {
      manager.submit(paint_mask_ps_, view);
    }
    if (show_tiled_image_border_) {
      manager.submit(image_border_ps_, view);
    }
    if (show_wireframe_) {
      manager.submit(wireframe_ps_, view);
    }
    if (show_mesh_analysis_) {
      manager.submit(analysis_ps_, view);
    }
    if (show_face_overlay_ || select_face_) {
      manager.submit(faces_ps_, view);
    }
    if (show_uv_edit_) {
      manager.submit(edges_ps_, view);
    }
    if (select_face_dots_) {
      manager.submit(facedots_ps_, view);
    }
    if (select_vert_) {
      manager.submit(verts_ps_, view);
    }
    if (show_stencil_) {
      manager.submit(brush_stencil_ps_, view);
    }

    GPU_debug_group_end();
  }

  void draw_on_render(gpu::FrameBuffer *framebuffer, Manager &manager, View &view) final
  {
    if (!enabled_) {
      return;
    }

    GPU_framebuffer_bind(framebuffer);
    /* Mask in #MASK_OVERLAY_COMBINED mode renders onto the render framebuffer and modifies the
     * image in scene referred color space. The #MASK_OVERLAY_ALPHACHANNEL renders onto the overlay
     * framebuffer. */
    if (show_mask_ && (mask_mode_ == MASK_OVERLAY_COMBINED)) {
      manager.submit(paint_mask_ps_, view);
    }
  }

 private:
  static OVERLAY_UVLineStyle edit_uv_line_style_from_space_image(const SpaceImage *sima)
  {
    const bool is_uv_editor = sima->mode == SI_MODE_UV;
    if (is_uv_editor) {
      switch (sima->dt_uv) {
        case SI_UVDT_OUTLINE:
          return OVERLAY_UV_LINE_STYLE_OUTLINE;
        case SI_UVDT_BLACK:
          return OVERLAY_UV_LINE_STYLE_BLACK;
        case SI_UVDT_WHITE:
          return OVERLAY_UV_LINE_STYLE_WHITE;
        case SI_UVDT_DASH:
          return OVERLAY_UV_LINE_STYLE_DASH;
        default:
          return OVERLAY_UV_LINE_STYLE_BLACK;
      }
    }
    else {
      return OVERLAY_UV_LINE_STYLE_SHADOW;
    }
  }

  /* TODO(jbakker): the GPU texture should be cached with the mask. */
  void paint_mask_texture_ensure(Mask *mask, const int2 &resolution, const float2 &aspect)
  {
    const int width = resolution.x;
    const int height = floor(float(resolution.y) * (aspect.y / aspect.x));
    float *buffer = MEM_new_array_uninitialized<float>(height * width, __func__);

    MaskRasterHandle *handle = BKE_maskrasterize_handle_new();
    BKE_maskrasterize_handle_init(handle, mask, width, height, true, true, true);
    BKE_maskrasterize_buffer(handle, width, height, buffer);
    BKE_maskrasterize_handle_free(handle);

    mask_texture_.free();
    mask_texture_.ensure_2d(
        gpu::TextureFormat::SFLOAT_16, int2(width, height), GPU_TEXTURE_USAGE_SHADER_READ, buffer);

    MEM_delete(buffer);
  }
};

}  // namespace blender::draw::overlay
