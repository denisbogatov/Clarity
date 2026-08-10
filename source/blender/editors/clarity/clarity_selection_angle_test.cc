/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "testing/testing.h"

#include <array>

#include "BLI_math_base.h"

#include "BKE_gtest_base.hh"

#include "DNA_scene_types.h"

#include "bmesh.hh"

#include "clarity_tools.hh"

namespace blender::ed::clarity::tests {

/**
 * Three equally sized quads form a strip with a 30-degree fold followed by a 60-degree fold.
 *
 * The fixture exposes an unambiguous propagation boundary for every component domain: face normals
 * are 0, 30 and 90 degrees; normals at the two shared vertex rows are 15 and 60 degrees; and an
 * edge on a fold averages the normals of the faces on its sides.
 */
class SelectionByAngleTest : public bke::BlenderGTestBase {
 protected:
  BMesh *bm = nullptr;
  std::array<BMVert *, 8> verts{};
  std::array<BMFace *, 3> faces{};

  void SetUp() override
  {
    BMeshCreateParams create_params{};
    create_params.use_toolflags = false;
    bm = BM_mesh_create(&bm_mesh_allocsize_default, &create_params);

    const float coordinates[8][3] = {
        {0.0f, 0.0f, 0.0f},
        {1.0f, 0.0f, 0.0f},
        {1.0f, 1.0f, 0.0f},
        {0.0f, 1.0f, 0.0f},
        {1.8660254f, 0.0f, 0.5f},
        {1.8660254f, 1.0f, 0.5f},
        {1.8660254f, 0.0f, 1.5f},
        {1.8660254f, 1.0f, 1.5f},
    };
    for (int i = 0; i < int(verts.size()); i++) {
      verts[i] = BM_vert_create(bm, coordinates[i], nullptr, BM_CREATE_NOP);
    }

    BMVert *face_verts[4];
    face_verts[0] = verts[0];
    face_verts[1] = verts[1];
    face_verts[2] = verts[2];
    face_verts[3] = verts[3];
    faces[0] = BM_face_create_verts(bm, face_verts, 4, nullptr, BM_CREATE_NOP, true);

    face_verts[0] = verts[1];
    face_verts[1] = verts[4];
    face_verts[2] = verts[5];
    face_verts[3] = verts[2];
    faces[1] = BM_face_create_verts(bm, face_verts, 4, nullptr, BM_CREATE_NOP, true);

    face_verts[0] = verts[4];
    face_verts[1] = verts[6];
    face_verts[2] = verts[7];
    face_verts[3] = verts[5];
    faces[2] = BM_face_create_verts(bm, face_verts, 4, nullptr, BM_CREATE_NOP, true);

    BM_mesh_normals_update(bm);
  }

  void TearDown() override
  {
    BM_mesh_free(bm);
  }

  void deselect_all()
  {
    BM_mesh_elem_hflag_disable_all(bm, BM_VERT | BM_EDGE | BM_FACE, BM_ELEM_SELECT, false);
  }

  BMEdge *edge(const int first, const int second)
  {
    return BM_edge_exists(verts[first], verts[second]);
  }
};

TEST_F(SelectionByAngleTest, FacesStopAtTheFirstFoldOutsideTheTolerance)
{
  BM_face_select_set(bm, faces[0], true);

  EXPECT_TRUE(selection_by_angle_propagate(*bm, SCE_SELECT_FACE, DEG2RADF(45.0f)));
  EXPECT_TRUE(BM_elem_flag_test(faces[0], BM_ELEM_SELECT));
  EXPECT_TRUE(BM_elem_flag_test(faces[1], BM_ELEM_SELECT));
  EXPECT_FALSE(BM_elem_flag_test(faces[2], BM_ELEM_SELECT));

  EXPECT_TRUE(selection_by_angle_propagate(*bm, SCE_SELECT_FACE, DEG2RADF(90.0f)));
  EXPECT_TRUE(BM_elem_flag_test(faces[2], BM_ELEM_SELECT));
}

TEST_F(SelectionByAngleTest, OneDegreeKeepsAFlatPatchFromCrossingTheFirstFold)
{
  BM_face_select_set(bm, faces[0], true);

  EXPECT_FALSE(selection_by_angle_propagate(*bm, SCE_SELECT_FACE, DEG2RADF(1.0f)));
  EXPECT_TRUE(BM_elem_flag_test(faces[0], BM_ELEM_SELECT));
  EXPECT_FALSE(BM_elem_flag_test(faces[1], BM_ELEM_SELECT));
  EXPECT_FALSE(BM_elem_flag_test(faces[2], BM_ELEM_SELECT));
}

TEST_F(SelectionByAngleTest, EdgesPropagateUsingTheirAveragedSurfaceNormals)
{
  BMEdge *seed = edge(0, 1);
  BMEdge *first_fold = edge(1, 2);
  BMEdge *second_fold = edge(4, 5);
  ASSERT_NE(seed, nullptr);
  ASSERT_NE(first_fold, nullptr);
  ASSERT_NE(second_fold, nullptr);
  BM_edge_select_set(bm, seed, true);

  EXPECT_TRUE(selection_by_angle_propagate(*bm, SCE_SELECT_EDGE, DEG2RADF(20.0f)));
  EXPECT_TRUE(BM_elem_flag_test(first_fold, BM_ELEM_SELECT));
  EXPECT_FALSE(BM_elem_flag_test(second_fold, BM_ELEM_SELECT));

  EXPECT_TRUE(selection_by_angle_propagate(*bm, SCE_SELECT_EDGE, DEG2RADF(45.0f)));
  EXPECT_TRUE(BM_elem_flag_test(second_fold, BM_ELEM_SELECT));
  EXPECT_EQ(bm->totedgesel, bm->totedge);
}

TEST_F(SelectionByAngleTest, VerticesUseVertexNormalsWithoutLosingValidEndpoints)
{
  BM_vert_select_set(bm, verts[0], true);

  EXPECT_TRUE(selection_by_angle_propagate(*bm, SCE_SELECT_VERTEX, DEG2RADF(20.0f)));
  EXPECT_TRUE(BM_elem_flag_test(verts[1], BM_ELEM_SELECT));
  EXPECT_TRUE(BM_elem_flag_test(verts[2], BM_ELEM_SELECT));
  EXPECT_TRUE(BM_elem_flag_test(verts[3], BM_ELEM_SELECT));
  EXPECT_FALSE(BM_elem_flag_test(verts[4], BM_ELEM_SELECT));
  EXPECT_FALSE(BM_elem_flag_test(verts[5], BM_ELEM_SELECT));

  EXPECT_TRUE(selection_by_angle_propagate(*bm, SCE_SELECT_VERTEX, DEG2RADF(45.0f)));
  EXPECT_EQ(bm->totvertsel, bm->totvert);
}

TEST_F(SelectionByAngleTest, OneHundredEightyDegreesTraversesTheWholeConnectedDomain)
{
  BM_face_select_set(bm, faces[0], true);
  EXPECT_TRUE(selection_by_angle_propagate(*bm, SCE_SELECT_FACE, DEG2RADF(180.0f)));
  EXPECT_EQ(bm->totfacesel, bm->totface);

  deselect_all();
  BM_edge_select_set(bm, edge(0, 1), true);
  EXPECT_TRUE(selection_by_angle_propagate(*bm, SCE_SELECT_EDGE, DEG2RADF(180.0f)));
  EXPECT_EQ(bm->totedgesel, bm->totedge);

  deselect_all();
  BM_vert_select_set(bm, verts[0], true);
  EXPECT_TRUE(selection_by_angle_propagate(*bm, SCE_SELECT_VERTEX, DEG2RADF(180.0f)));
  EXPECT_EQ(bm->totvertsel, bm->totvert);
}

}  // namespace blender::ed::clarity::tests
