/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include <optional>

#include "DNA_object_types.h"

#include "BLI_math_matrix_types.hh"
#include "BLI_math_vector_types.hh"

namespace blender {

struct Depsgraph;
struct Object;
struct Scene;

enum eClarityTransformChannel {
  CLARITY_TRANSFORM_CHANNEL_TRANSLATION = 0,
  CLARITY_TRANSFORM_CHANNEL_ROTATION = 1,
  CLARITY_TRANSFORM_CHANNEL_SCALE = 2,
};

struct ClarityConstraintChannelOutput {
  std::optional<double3> translation;
  std::optional<double3> rotation;
  std::optional<double3> scale;
  bool translation_mask[3] = {};
  bool rotation_mask[3] = {};
  bool scale_mask[3] = {};
};

struct ClarityConstraintEvalContext {
  Object &object;
  const double4x4 &parent_effect;
};

ClarityConstraint *BKE_clarity_constraint_add(Object &object,
                                         eClarityConstraintType type,
                                         const char *name);
ClarityConstraintTarget *BKE_clarity_constraint_target_add(ClarityConstraint &constraint,
                                                      Object &target,
                                                      double weight);
bool BKE_clarity_constraint_maintain_offset_set(Object &object,
                                             ClarityConstraint &constraint,
                                             bool enabled);
void BKE_clarity_constraint_remove(Object &object, ClarityConstraint &constraint);
void BKE_clarity_constraints_clear(Object &object);

double3 BKE_clarity_constraint_target_pivot_world_get(const Object &target);
bool BKE_clarity_point_constraint_evaluate(const ClarityConstraint &constraint,
                                        const ClarityConstraintEvalContext &context,
                                        ClarityConstraintChannelOutput &r_output);
void BKE_clarity_constraint_output_apply(Object &object,
                                      const ClarityConstraintChannelOutput &output);

void BKE_object_eval_clarity_channels_init(Depsgraph *depsgraph, Object *object);
void BKE_object_eval_clarity_constraints(Depsgraph *depsgraph, Scene *scene, Object *object);
void BKE_object_eval_clarity_local_transform(Depsgraph *depsgraph, Object *object);
void BKE_object_clarity_evaluated_channels_invalidate(Object &object);

bool BKE_object_clarity_channel_is_driven(const Object &object,
                                       eClarityTransformChannel channel,
                                       int axis);

}  // namespace blender
