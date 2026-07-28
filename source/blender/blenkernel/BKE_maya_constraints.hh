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

enum eMayaTransformChannel {
  MAYA_TRANSFORM_CHANNEL_TRANSLATION = 0,
  MAYA_TRANSFORM_CHANNEL_ROTATION = 1,
  MAYA_TRANSFORM_CHANNEL_SCALE = 2,
};

struct MayaConstraintChannelOutput {
  std::optional<double3> translation;
  std::optional<double3> rotation;
  std::optional<double3> scale;
  bool translation_mask[3] = {};
  bool rotation_mask[3] = {};
  bool scale_mask[3] = {};
};

struct MayaConstraintEvalContext {
  Object &object;
  const double4x4 &parent_effect;
};

MayaConstraint *BKE_maya_constraint_add(Object &object,
                                         eMayaConstraintType type,
                                         const char *name);
MayaConstraintTarget *BKE_maya_constraint_target_add(MayaConstraint &constraint,
                                                      Object &target,
                                                      double weight);
bool BKE_maya_constraint_maintain_offset_set(Object &object,
                                             MayaConstraint &constraint,
                                             bool enabled);
void BKE_maya_constraint_remove(Object &object, MayaConstraint &constraint);
void BKE_maya_constraints_clear(Object &object);

double3 BKE_maya_constraint_target_pivot_world_get(const Object &target);
bool BKE_maya_point_constraint_evaluate(const MayaConstraint &constraint,
                                        const MayaConstraintEvalContext &context,
                                        MayaConstraintChannelOutput &r_output);
void BKE_maya_constraint_output_apply(Object &object,
                                      const MayaConstraintChannelOutput &output);

void BKE_object_eval_maya_channels_init(Depsgraph *depsgraph, Object *object);
void BKE_object_eval_maya_constraints(Depsgraph *depsgraph, Scene *scene, Object *object);
void BKE_object_eval_maya_local_transform(Depsgraph *depsgraph, Object *object);
void BKE_object_maya_evaluated_channels_invalidate(Object &object);

bool BKE_object_maya_channel_is_driven(const Object &object,
                                       eMayaTransformChannel channel,
                                       int axis);

}  // namespace blender
