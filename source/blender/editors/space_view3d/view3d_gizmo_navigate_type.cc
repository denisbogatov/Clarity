/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup wm
 *
 * \name Custom Orientation/Navigation Gizmo for the 3D View
 *
 * \brief Clarity-style view cube for axis selection and view rotation.
 *
 * - scale_basis: used for the size.
 * - matrix_basis: used for the location.
 * - matrix_offset: used to store the orientation.
 */

#include <algorithm>
#include <cfloat>
#include <cstdlib>
#include <cstring>

#include "BLI_assert.h"
#include "BLI_math_matrix.h"
#include "BLI_math_vector.h"
#include "BLI_sort_utils.h"

#include "BKE_context.hh"

#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_state.hh"

#include "BLF_api.hh"
#include "BLT_translation.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_intern.hh"

namespace blender {

/* Radius of the entire background. */
#define WIDGET_RADIUS ((U.gizmo_size_navigate_v3d / 2.0f) * UI_SCALE_FAC)

/* Clarity-style view-cube dimensions in normalized gizmo space. */
#define VIEWCUBE_HALF_SIZE 0.68f
#define VIEWCUBE_BEVEL_SIZE 0.10f
#define VIEWCUBE_BOUND_RADIUS (VIEWCUBE_HALF_SIZE * 1.74f)
#define VIEWCUBE_LINE_WIDTH ((U.gizmo_size_navigate_v3d / 65.0f) * UI_SCALE_FAC)
/* Render labels at a higher internal resolution, then scale them onto each face. */
#define VIEWCUBE_TEXT_SIZE (WIDGET_RADIUS * 0.60f)

struct ViewCubeFace {
  float depth;
  char index;
  char axis;
  bool is_pos;
};

struct ViewCubePolygon {
  float depth;
  float vertices[4][3];
  float shade;
  char vertex_count;
  char face_index;
  char kind;
};

static void viewcube_main_face_vertices(const int axis,
                                        const bool is_pos,
                                        float r_vertices[4][3])
{
  const int axis_u = (axis + 1) % 3;
  const int axis_v = (axis + 2) % 3;
  const float side = is_pos ? VIEWCUBE_HALF_SIZE : -VIEWCUBE_HALF_SIZE;
  const float inner = VIEWCUBE_HALF_SIZE - VIEWCUBE_BEVEL_SIZE;
  const float coordinates[4][2] = {{-1.0f, -1.0f},
                                   {1.0f, -1.0f},
                                   {1.0f, 1.0f},
                                   {-1.0f, 1.0f}};

  for (int i = 0; i < 4; i++) {
    zero_v3(r_vertices[i]);
    r_vertices[i][axis] = side;
    r_vertices[i][axis_u] = coordinates[i][0] * inner;
    r_vertices[i][axis_v] = coordinates[i][1] * inner;
  }
}

static void viewcube_bevel_vertices(const int axis_a,
                                    const int axis_b,
                                    const int sign_a,
                                    const int sign_b,
                                    float r_vertices[4][3])
{
  const int axis_c = 3 - axis_a - axis_b;
  const float inner = VIEWCUBE_HALF_SIZE - VIEWCUBE_BEVEL_SIZE;
  zero_v3(r_vertices[0]);
  zero_v3(r_vertices[1]);
  zero_v3(r_vertices[2]);
  zero_v3(r_vertices[3]);

  r_vertices[0][axis_a] = sign_a * VIEWCUBE_HALF_SIZE;
  r_vertices[0][axis_b] = sign_b * inner;
  r_vertices[0][axis_c] = -inner;
  r_vertices[1][axis_a] = sign_a * inner;
  r_vertices[1][axis_b] = sign_b * VIEWCUBE_HALF_SIZE;
  r_vertices[1][axis_c] = -inner;
  r_vertices[2][axis_a] = sign_a * inner;
  r_vertices[2][axis_b] = sign_b * VIEWCUBE_HALF_SIZE;
  r_vertices[2][axis_c] = inner;
  r_vertices[3][axis_a] = sign_a * VIEWCUBE_HALF_SIZE;
  r_vertices[3][axis_b] = sign_b * inner;
  r_vertices[3][axis_c] = inner;
}

static void viewcube_project_point(const wmGizmo *gz, const float point[3], float r_point[2])
{
  r_point[0] = point[0] * gz->matrix_offset[0][0] + point[1] * gz->matrix_offset[1][0] +
               point[2] * gz->matrix_offset[2][0];
  r_point[1] = point[0] * gz->matrix_offset[0][1] + point[1] * gz->matrix_offset[1][1] +
               point[2] * gz->matrix_offset[2][1];
}

static bool viewcube_point_in_quad(const float point[2], const float quad[4][2])
{
  bool has_negative = false;
  bool has_positive = false;
  for (int i = 0; i < 4; i++) {
    const float *a = quad[i];
    const float *b = quad[(i + 1) % 4];
    const float cross = (b[0] - a[0]) * (point[1] - a[1]) -
                        (b[1] - a[1]) * (point[0] - a[0]);
    has_negative |= cross < -1e-5f;
    has_positive |= cross > 1e-5f;
  }
  return !(has_negative && has_positive);
}

static const char *viewcube_face_label(const int index)
{
  static const char *labels[6] = {
      N_("LEFT"), N_("RIGHT"), N_("FRONT"), N_("BACK"), N_("BOTTOM"), N_("TOP")};
  return IFACE_(labels[index]);
}

static void viewcube_face_text_matrix(const wmGizmo *gz,
                                      const ViewCubeFace &face,
                                      float r_matrix[4][4])
{
  unit_m4(r_matrix);
  zero_v3(r_matrix[0]);
  zero_v3(r_matrix[1]);
  zero_v3(r_matrix[2]);

  const float sign = face.is_pos ? 1.0f : -1.0f;
  if (face.axis == 0) {
    /* U = +/-Y, V = Z. */
    r_matrix[0][1] = sign;
    r_matrix[1][2] = 1.0f;
    r_matrix[2][0] = sign;
  }
  else if (face.axis == 1) {
    /* U = -/+X, V = Z. */
    r_matrix[0][0] = -sign;
    r_matrix[1][2] = 1.0f;
    r_matrix[2][1] = sign;
  }
  else {
    /* U = +/-X, V = Y. */
    r_matrix[0][0] = sign;
    r_matrix[1][1] = 1.0f;
    r_matrix[2][2] = sign;
  }

  /* Keep labels readable when a face rotates past a screen-space half turn. */
  float screen_u[2];
  float screen_v[2];
  viewcube_project_point(gz, r_matrix[0], screen_u);
  viewcube_project_point(gz, r_matrix[1], screen_v);
  if (screen_u[0] < 0.0f ||
      (fabsf(screen_u[0]) < 1e-5f && screen_v[1] < 0.0f))
  {
    negate_v3(r_matrix[0]);
    negate_v3(r_matrix[1]);
  }
}

static void gizmo_axis_draw(const bContext * /*C*/, wmGizmo *gz)
{
  ViewCubeFace faces[6] = {
      {-gz->matrix_offset[0][2], 0, 0, false},
      {+gz->matrix_offset[0][2], 1, 0, true},
      {-gz->matrix_offset[1][2], 2, 1, false},
      {+gz->matrix_offset[1][2], 3, 1, true},
      {-gz->matrix_offset[2][2], 4, 2, false},
      {+gz->matrix_offset[2][2], 5, 2, true},
  };
  qsort(faces, ARRAY_SIZE(faces), sizeof(faces[0]), BLI_sortutil_cmp_float);

  float matrix_screen[4][4];
  float matrix_unit[4][4];
  unit_m4(matrix_unit);

  wmGizmoMatrixParams params{};
  params.matrix_offset = matrix_unit;
  WM_gizmo_calc_matrix_final_params(gz, &params, matrix_screen);
  GPU_matrix_push();
  GPU_matrix_mul(matrix_screen);

  GPUVertFormat *format = immVertexFormat();
  const uint pos_id = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32_32);

  const int font_id = BLF_default();
  BLF_disable(font_id, BLF_ROTATION | BLF_SHADOW | BLF_ASPECT | BLF_WORD_WRAP);
  BLF_enable(font_id, BLF_BOLD);
  BLF_size(font_id, VIEWCUBE_TEXT_SIZE);
  BLF_position(font_id, 0, 0, 0);

  bool use_project_matrix = (gz->scale_final >= -GPU_MATRIX_ORTHO_CLIP_NEAR_DEFAULT);
  if (use_project_matrix) {
    GPU_matrix_push_projection();
    GPU_matrix_ortho_set_z(-gz->scale_final, gz->scale_final);
  }

  GPU_matrix_mul(gz->matrix_offset);

  ViewCubePolygon polygons[26];
  int polygon_count = 0;
  const auto add_polygon = [&](const float vertices[][3],
                               const int vertex_count,
                               const float shade,
                               const int kind,
                               const int face_index) {
    ViewCubePolygon &polygon = polygons[polygon_count++];
    polygon.depth = 0.0f;
    polygon.shade = shade;
    polygon.vertex_count = vertex_count;
    polygon.face_index = face_index;
    polygon.kind = kind;
    for (int i = 0; i < vertex_count; i++) {
      copy_v3_v3(polygon.vertices[i], vertices[i]);
      polygon.depth += vertices[i][0] * gz->matrix_offset[0][2] +
                       vertices[i][1] * gz->matrix_offset[1][2] +
                       vertices[i][2] * gz->matrix_offset[2][2];
    }
    polygon.depth /= vertex_count;
  };

  /* Six inset primary faces. */
  for (const ViewCubeFace &face : faces) {
    float vertices[4][3];
    viewcube_main_face_vertices(face.axis, face.is_pos, vertices);
    const float shade = 0.68f + 0.10f * ((face.depth + 1.0f) * 0.5f);
    add_polygon(vertices, 4, shade, 0, face.index);
  }

  /* Twelve bevel polygons connecting pairs of primary faces. */
  const float inner = VIEWCUBE_HALF_SIZE - VIEWCUBE_BEVEL_SIZE;
  int bevel_index = 0;
  for (int axis_a = 0; axis_a < 3; axis_a++) {
    for (int axis_b = axis_a + 1; axis_b < 3; axis_b++) {
      for (int sign_a = -1; sign_a <= 1; sign_a += 2) {
        for (int sign_b = -1; sign_b <= 1; sign_b += 2) {
          float vertices[4][3];
          viewcube_bevel_vertices(axis_a, axis_b, sign_a, sign_b, vertices);
          add_polygon(vertices, 4, 0.61f, 1, bevel_index++);
        }
      }
    }
  }

  /* Eight triangular corner polygons. */
  for (int sign_x = -1; sign_x <= 1; sign_x += 2) {
    for (int sign_y = -1; sign_y <= 1; sign_y += 2) {
      for (int sign_z = -1; sign_z <= 1; sign_z += 2) {
        const float vertices[3][3] = {
            {sign_x * VIEWCUBE_HALF_SIZE, sign_y * inner, sign_z * inner},
            {sign_x * inner, sign_y * VIEWCUBE_HALF_SIZE, sign_z * inner},
            {sign_x * inner, sign_y * inner, sign_z * VIEWCUBE_HALF_SIZE},
        };
        add_polygon(vertices, 3, 0.54f, 2, -1);
      }
    }
  }
  BLI_assert(polygon_count == ARRAY_SIZE(polygons));
  qsort(polygons, polygon_count, sizeof(polygons[0]), BLI_sortutil_cmp_float);

  GPU_blend(GPU_BLEND_ALPHA);
  GPU_line_smooth(true);
  GPU_polygon_smooth(true);
  for (const ViewCubePolygon &polygon : polygons) {
    const bool is_highlight =
        (polygon.kind == 0 && polygon.face_index + 1 == gz->highlight_part) ||
        (polygon.kind == 1 && polygon.face_index + 7 == gz->highlight_part);
    const float face_color[4] = {
        is_highlight ? 0.16f : polygon.shade,
        is_highlight ? 0.48f : polygon.shade,
        is_highlight ? 0.92f : polygon.shade,
        0.98f,
    };
    const float outline_color[4] = {
        is_highlight ? 0.08f : 0.12f,
        is_highlight ? 0.30f : 0.12f,
        is_highlight ? 0.70f : 0.12f,
        1.0f,
    };

    immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
    immUniformColor4fv(face_color);
    immBegin(GPU_PRIM_TRIS, polygon.vertex_count == 4 ? 6 : 3);
    immVertex3fv(pos_id, polygon.vertices[0]);
    immVertex3fv(pos_id, polygon.vertices[1]);
    immVertex3fv(pos_id, polygon.vertices[2]);
    if (polygon.vertex_count == 4) {
      immVertex3fv(pos_id, polygon.vertices[0]);
      immVertex3fv(pos_id, polygon.vertices[2]);
      immVertex3fv(pos_id, polygon.vertices[3]);
    }
    immEnd();

    GPU_line_width(VIEWCUBE_LINE_WIDTH);
    immUniformColor4fv(outline_color);
    immBegin(GPU_PRIM_LINE_LOOP, polygon.vertex_count);
    for (int i = 0; i < polygon.vertex_count; i++) {
      immVertex3fv(pos_id, polygon.vertices[i]);
    }
    immEnd();
    immUnbindProgram();
  }

  GPU_polygon_smooth(false);

  /* Face labels are drawn last so bevel polygons cannot cover them. */
  for (const ViewCubeFace &face : faces) {
    const bool is_highlight = face.index + 1 == gz->highlight_part;

    if (face.depth > 0.20f) {
      const char *label = viewcube_face_label(face.index);
      float label_width, label_height;
      BLF_width_and_height(font_id, label, strlen(label), &label_width, &label_height);

      float center[3] = {0.0f, 0.0f, 0.0f};
      center[face.axis] = (face.is_pos ? VIEWCUBE_HALF_SIZE : -VIEWCUBE_HALF_SIZE) * 1.01f;
      const float label_scale = std::min((inner * 2.0f * 0.72f) / label_width,
                                         (inner * 2.0f * 0.42f) / label_height);
      float text_matrix[4][4];
      viewcube_face_text_matrix(gz, face, text_matrix);

      GPU_matrix_push();
      GPU_matrix_translate_3fv(center);
      GPU_matrix_mul(text_matrix);
      GPU_matrix_scale_2f(label_scale, label_scale);
      GPU_matrix_translate_2f(-label_width * 0.5f, -label_height * 0.5f);
      const float text_color[4] = {
          is_highlight ? 1.0f : 0.08f,
          is_highlight ? 1.0f : 0.08f,
          is_highlight ? 1.0f : 0.08f,
          1.0f,
      };
      BLF_color4fv(font_id, text_color);
      BLF_draw(font_id, label, strlen(label));
      GPU_matrix_pop();
    }
  }

  GPU_line_width(1.0f);
  GPU_line_smooth(false);
  if (use_project_matrix) {
    GPU_matrix_pop_projection();
  }

  GPU_blend(GPU_BLEND_NONE);
  BLF_disable(font_id, BLF_BOLD);
  GPU_matrix_pop();
}

static int gizmo_axis_test_select(bContext * /*C*/, wmGizmo *gz, const int mval[2])
{
  float point_local[2] = {float(mval[0]), float(mval[1])};
  sub_v2_v2(point_local, gz->matrix_basis[3]);
  mul_v2_fl(point_local, 1.0f / gz->scale_final);

  if (len_squared_v2(point_local) > VIEWCUBE_BOUND_RADIUS * VIEWCUBE_BOUND_RADIUS) {
    return -1;
  }

  float best_depth = -FLT_MAX;
  int best_part = -1;
  for (int axis = 0; axis < 3; axis++) {
    for (int is_pos = 0; is_pos < 2; is_pos++) {
      float vertices[4][3];
      float quad[4][2];
      viewcube_main_face_vertices(axis, is_pos != 0, vertices);
      for (int i = 0; i < 4; i++) {
        viewcube_project_point(gz, vertices[i], quad[i]);
      }

      const float depth = gz->matrix_offset[axis][2] * (is_pos ? 1.0f : -1.0f);
      if (depth > best_depth && viewcube_point_in_quad(point_local, quad)) {
        best_depth = depth;
        best_part = axis * 2 + is_pos + 1;
      }
    }
  }

  int bevel_index = 0;
  for (int axis_a = 0; axis_a < 3; axis_a++) {
    for (int axis_b = axis_a + 1; axis_b < 3; axis_b++) {
      for (int sign_a = -1; sign_a <= 1; sign_a += 2) {
        for (int sign_b = -1; sign_b <= 1; sign_b += 2) {
          float vertices[4][3];
          float quad[4][2];
          viewcube_bevel_vertices(axis_a, axis_b, sign_a, sign_b, vertices);
          float depth = 0.0f;
          for (int i = 0; i < 4; i++) {
            viewcube_project_point(gz, vertices[i], quad[i]);
            depth += vertices[i][0] * gz->matrix_offset[0][2] +
                     vertices[i][1] * gz->matrix_offset[1][2] +
                     vertices[i][2] * gz->matrix_offset[2][2];
          }
          depth *= 0.25f;
          if (depth > best_depth && viewcube_point_in_quad(point_local, quad)) {
            best_depth = depth;
            best_part = bevel_index + 7;
          }
          bevel_index++;
        }
      }
    }
  }
  return best_part;
}

static int gizmo_axis_cursor_get(wmGizmo * /*gz*/)
{
  return WM_CURSOR_DEFAULT;
}

static bool gizmo_axis_screen_bounds_get(const bContext *C, wmGizmo *gz, rcti *r_bounding_box)
{
  ScrArea *area = CTX_wm_area(C);
  const float rad = WIDGET_RADIUS * VIEWCUBE_BOUND_RADIUS;
  r_bounding_box->xmin = gz->matrix_basis[3][0] + area->totrct.xmin - rad;
  r_bounding_box->ymin = gz->matrix_basis[3][1] + area->totrct.ymin - rad;
  r_bounding_box->xmax = gz->matrix_basis[3][0] + area->totrct.xmin + rad;
  r_bounding_box->ymax = gz->matrix_basis[3][1] + area->totrct.ymin + rad;
  return true;
}

static void gizmo_axis_setup(wmGizmo *gz)
{
  WM_gizmo_set_flag(gz, WM_GIZMO_NO_GROUPING, true);
}

void VIEW3D_GT_navigate_rotate(wmGizmoType *gzt)
{
  /* identifiers */
  gzt->idname = "VIEW3D_GT_navigate_rotate";

  /* API callbacks. */
  gzt->setup = gizmo_axis_setup;
  gzt->draw = gizmo_axis_draw;
  gzt->test_select = gizmo_axis_test_select;
  gzt->cursor_get = gizmo_axis_cursor_get;
  gzt->screen_bounds_get = gizmo_axis_screen_bounds_get;

  gzt->struct_size = sizeof(wmGizmo);
}

}  // namespace blender
