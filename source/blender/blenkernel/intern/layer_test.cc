/* SPDX-FileCopyrightText: 2020 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */
#include "testing/testing.h"

#include "BKE_appdir.hh"
#include "BKE_gtest_base.hh"
#include "BKE_idtype.hh"
#include "BKE_layer.hh"
#include "BKE_main.hh"
#include "BKE_scene.hh"

#include "BLI_string.h"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"

#include "RE_engine.h"

#include "IMB_imbuf.hh"

#include "CLG_log.h"

#include "RNA_access.hh"
#include "RNA_define.hh"
#include "RNA_prototypes.hh"

namespace blender::bke::tests {

class ViewLayerTest : public bke::BlenderGTestBase {};

TEST_F(ViewLayerTest, clarity_parent_viewport_visibility_is_inherited)
{
  Object parent = {};
  Object child = {};
  child.parent = &parent;

  Base child_base = {};
  child_base.object = &child;
  child_base.flag = BASE_SELECTED;
  child_base.flag_from_collection = BASE_ENABLED_VIEWPORT | BASE_ENABLED_RENDER | BASE_SELECTABLE |
                                    BASE_ENABLED_AND_MAYBE_VISIBLE_IN_VIEWPORT |
                                    BASE_ENABLED_AND_VISIBLE_IN_DEFAULT_VIEWPORT;

  parent.visibility_flag = OB_HIDE_VIEWPORT;
  BKE_base_eval_flags(&child_base);
  EXPECT_EQ(child.visibility_flag & OB_HIDE_VIEWPORT, 0);
  EXPECT_EQ(child_base.flag & BASE_ENABLED_VIEWPORT, 0);
  EXPECT_NE(child_base.flag & BASE_SELECTED, 0);

  parent.visibility_flag = 0;
  BKE_base_eval_flags(&child_base);
  EXPECT_NE(child_base.flag & BASE_ENABLED_VIEWPORT, 0);
  EXPECT_NE(child_base.flag & BASE_SELECTED, 0);
}

TEST_F(ViewLayerTest, clarity_eye_hidden_selection_survives_evaluation)
{
  Object object = {};
  Base base = {};
  base.object = &object;
  base.flag = BASE_SELECTED | BASE_HIDDEN;
  base.flag_from_collection = BASE_ENABLED_VIEWPORT | BASE_ENABLED_RENDER | BASE_SELECTABLE |
                              BASE_ENABLED_AND_MAYBE_VISIBLE_IN_VIEWPORT |
                              BASE_ENABLED_AND_VISIBLE_IN_DEFAULT_VIEWPORT;

  BKE_base_eval_flags(&base);
  EXPECT_NE(base.flag & BASE_HIDDEN, 0);
  EXPECT_NE(base.flag & BASE_SELECTED, 0);

  base.flag &= ~BASE_HIDDEN;
  BKE_base_eval_flags(&base);
  EXPECT_EQ(base.flag & BASE_HIDDEN, 0);
  EXPECT_NE(base.flag & BASE_SELECTED, 0);
}

TEST_F(ViewLayerTest, aov_unique_names)
{
  Main *bmain = BKE_main_new();
  Scene *scene = BKE_scene_add(bmain, "Scene");
  ViewLayer *view_layer = static_cast<ViewLayer *>(scene->view_layers.first);

  RenderEngineType *engine_type = RE_engines_find(scene->r.engine);
  RenderEngine *engine = RE_engine_create(engine_type);

  EXPECT_FALSE(BKE_view_layer_has_valid_aov(view_layer));
  EXPECT_EQ(view_layer->active_aov, nullptr);

  /* Add an AOV */
  ViewLayerAOV *aov1 = BKE_view_layer_add_aov(view_layer);
  BKE_view_layer_verify_aov(engine, scene, view_layer);
  EXPECT_EQ(view_layer->active_aov, aov1);
  EXPECT_TRUE(BKE_view_layer_has_valid_aov(view_layer));
  EXPECT_FALSE((aov1->flag & AOV_CONFLICT) != 0);

  /* Add a second AOV */
  ViewLayerAOV *aov2 = BKE_view_layer_add_aov(view_layer);
  BKE_view_layer_verify_aov(engine, scene, view_layer);
  EXPECT_EQ(view_layer->active_aov, aov2);
  EXPECT_TRUE(BKE_view_layer_has_valid_aov(view_layer));
  EXPECT_FALSE((aov1->flag & AOV_CONFLICT) != 0);
  EXPECT_FALSE((aov2->flag & AOV_CONFLICT) != 0);
  EXPECT_TRUE(STREQ(aov1->name, "AOV"));
  EXPECT_TRUE(STREQ(aov2->name, "AOV_001"));

  /* Revert previous resolution */
  STRNCPY(aov2->name, "AOV");
  BKE_view_layer_verify_aov(engine, scene, view_layer);
  EXPECT_TRUE(BKE_view_layer_has_valid_aov(view_layer));
  EXPECT_FALSE((aov1->flag & AOV_CONFLICT) != 0);
  EXPECT_FALSE((aov2->flag & AOV_CONFLICT) != 0);
  EXPECT_TRUE(STREQ(aov1->name, "AOV"));
  EXPECT_TRUE(STREQ(aov2->name, "AOV_001"));

  /* Resolve by removing AOV resolution */
  BKE_view_layer_remove_aov(view_layer, aov2);
  aov2 = nullptr;
  BKE_view_layer_verify_aov(engine, scene, view_layer);
  EXPECT_TRUE(BKE_view_layer_has_valid_aov(view_layer));
  EXPECT_FALSE((aov1->flag & AOV_CONFLICT) != 0);

  BKE_main_free(bmain);

  RE_engine_free(engine);
}

static void test_render_pass_conflict(Scene *scene,
                                      RenderEngine *engine,
                                      ViewLayer *view_layer,
                                      ViewLayerAOV *aov,
                                      const char *render_pass_name,
                                      const char *rna_prop_name)
{
  PointerRNA ptr = RNA_pointer_create_discrete(&scene->id, RNA_ViewLayer, view_layer);
  RNA_boolean_set(&ptr, rna_prop_name, false);

  /* Rename to Conflicting name */
  STRNCPY(aov->name, render_pass_name);
  BKE_view_layer_verify_aov(engine, scene, view_layer);
  EXPECT_TRUE(BKE_view_layer_has_valid_aov(view_layer));
  EXPECT_FALSE((aov->flag & AOV_CONFLICT) != 0);
  EXPECT_TRUE(STREQ(aov->name, render_pass_name));

  /* Activate render pass */
  RNA_boolean_set(&ptr, rna_prop_name, true);
  BKE_view_layer_verify_aov(engine, scene, view_layer);
  EXPECT_FALSE(BKE_view_layer_has_valid_aov(view_layer));
  EXPECT_TRUE((aov->flag & AOV_CONFLICT) != 0);
  EXPECT_TRUE(STREQ(aov->name, render_pass_name));

  /* Deactivate render pass */
  RNA_boolean_set(&ptr, rna_prop_name, false);
  BKE_view_layer_verify_aov(engine, scene, view_layer);
  EXPECT_TRUE(BKE_view_layer_has_valid_aov(view_layer));
  EXPECT_FALSE((aov->flag & AOV_CONFLICT) != 0);
  EXPECT_TRUE(STREQ(aov->name, render_pass_name));
}

TEST_F(ViewLayerTest, aov_conflict)
{
  Main *bmain = BKE_main_new();
  Scene *scene = BKE_scene_add(bmain, "Scene");
  ViewLayer *view_layer = static_cast<ViewLayer *>(scene->view_layers.first);

  RenderEngineType *engine_type = RE_engines_find(scene->r.engine);
  RenderEngine *engine = RE_engine_create(engine_type);

  EXPECT_FALSE(BKE_view_layer_has_valid_aov(view_layer));
  EXPECT_EQ(view_layer->active_aov, nullptr);

  /* Add an AOV */
  ViewLayerAOV *aov = BKE_view_layer_add_aov(view_layer);
  BKE_view_layer_verify_aov(engine, scene, view_layer);
  EXPECT_EQ(view_layer->active_aov, aov);
  EXPECT_TRUE(BKE_view_layer_has_valid_aov(view_layer));
  EXPECT_FALSE((aov->flag & AOV_CONFLICT) != 0);

  test_render_pass_conflict(scene, engine, view_layer, aov, "Depth", "use_pass_z");
  test_render_pass_conflict(scene, engine, view_layer, aov, "Normal", "use_pass_normal");
  test_render_pass_conflict(scene, engine, view_layer, aov, "Mist", "use_pass_mist");
  test_render_pass_conflict(scene, engine, view_layer, aov, "Shadow", "use_pass_shadow");
  test_render_pass_conflict(
      scene, engine, view_layer, aov, "Ambient Occlusion", "use_pass_ambient_occlusion");
  test_render_pass_conflict(scene, engine, view_layer, aov, "Emission", "use_pass_emit");
  test_render_pass_conflict(scene, engine, view_layer, aov, "Environment", "use_pass_environment");
  test_render_pass_conflict(
      scene, engine, view_layer, aov, "Diffuse Direct", "use_pass_diffuse_direct");
  test_render_pass_conflict(
      scene, engine, view_layer, aov, "Diffuse Color", "use_pass_diffuse_color");
  test_render_pass_conflict(
      scene, engine, view_layer, aov, "Glossy Direct", "use_pass_glossy_direct");
  test_render_pass_conflict(
      scene, engine, view_layer, aov, "Glossy Color", "use_pass_glossy_color");

  BKE_main_free(bmain);
  RE_engine_free(engine);
}

}  // namespace blender::bke::tests
