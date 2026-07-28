/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup bke
 */

#include <algorithm>
#include <cmath>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_math_matrix.hh"
#include "BLI_math_vector.hh"
#include "BLI_string.h"

#include "BKE_maya_constraints.hh"
#include "BKE_object.hh"
#include "BKE_object_transform_maya.hh"
#include "BKE_object_types.hh"

#include "DEG_depsgraph.hh"

namespace blender {

MayaConstraint *BKE_maya_constraint_add(Object &object,
                                         const eMayaConstraintType type,
                                         const char *name)
{
  MayaConstraint *constraint = MEM_new<MayaConstraint>(__func__);
  constraint->type = type;
  STRNCPY(constraint->name, name);
  BLI_addtail(&object.maya_constraints, constraint);
  return constraint;
}

MayaConstraintTarget *BKE_maya_constraint_target_add(MayaConstraint &constraint,
                                                      Object &target,
                                                      const double weight)
{
  MayaConstraintTarget *constraint_target = MEM_new<MayaConstraintTarget>(__func__);
  constraint_target->object = &target;
  constraint_target->weight = weight;
  BLI_addtail(&constraint.targets, constraint_target);
  return constraint_target;
}

bool BKE_maya_constraint_maintain_offset_set(Object &object,
                                             MayaConstraint &constraint,
                                             const bool enabled)
{
  if (constraint.type != MAYA_CONSTRAINT_POINT) {
    return false;
  }
  const double3 constrained_position = BKE_maya_constraint_target_pivot_world_get(object);
  for (MayaConstraintTarget &target : constraint.targets) {
    const double3 offset = enabled && target.object != nullptr ?
                               constrained_position -
                                   BKE_maya_constraint_target_pivot_world_get(*target.object) :
                               double3(0.0);
    for (int axis = 0; axis < 3; axis++) {
      target.translate_offset[axis] = offset[axis];
    }
  }
  constraint.maintain_offset = enabled;
  return true;
}

void BKE_maya_constraint_remove(Object &object, MayaConstraint &constraint)
{
  BLI_freelistN(&constraint.targets);
  BLI_remlink(&object.maya_constraints, &constraint);
  MEM_delete(&constraint);
}

void BKE_maya_constraints_clear(Object &object)
{
  for (MayaConstraint &constraint : object.maya_constraints) {
    BLI_freelistN(&constraint.targets);
  }
  BLI_freelistN(&object.maya_constraints);
}

static double4x4 maya_parent_effect_get(const Object &object)
{
  if (object.parent == nullptr) {
    return double4x4::identity();
  }
  float parent_effect[4][4];
  BKE_object_get_parent_matrix(&object, object.parent, parent_effect);
  return double4x4(float4x4(parent_effect));
}

static const MayaObjectTransform &maya_evaluated_transform_get(const Object &object)
{
  if (object.runtime != nullptr && object.runtime->maya_transform.valid) {
    return object.runtime->maya_transform.evaluated;
  }
  return *object.maya_transform;
}

double3 BKE_maya_constraint_target_pivot_world_get(const Object &target)
{
  if (!BKE_object_uses_maya_transform(&target)) {
    return double3(target.object_to_world().location());
  }
  return BKE_maya_rotate_pivot_world_get(maya_evaluated_transform_get(target),
                                         maya_parent_effect_get(target));
}

bool BKE_maya_point_constraint_evaluate(const MayaConstraint &constraint,
                                        const MayaConstraintEvalContext &context,
                                        MayaConstraintChannelOutput &r_output)
{
  if (!constraint.enabled || constraint.influence <= 0.0) {
    return false;
  }

  double3 target_world(0.0);
  double total_weight = 0.0;
  for (const MayaConstraintTarget &target : constraint.targets) {
    if (target.object == nullptr || !std::isfinite(target.weight) || target.weight <= 0.0) {
      continue;
    }
    const double3 position = BKE_maya_constraint_target_pivot_world_get(*target.object) +
                             double3(target.translate_offset);
    target_world += position * target.weight;
    total_weight += target.weight;
  }
  if (total_weight <= 1.0e-12) {
    return false;
  }
  target_world /= total_weight;

  MayaObjectTransform &evaluated = context.object.runtime->maya_transform.evaluated;
  const double4x4 offset_parent(evaluated.offset_parent_matrix);
  const double4x4 prefix = evaluated.inherits_transform ?
                               context.parent_effect * offset_parent :
                               offset_parent;
  bool inverse_success;
  const double4x4 prefix_inverse = math::invert(prefix, inverse_success);
  if (!inverse_success) {
    return false;
  }

  const double3 constrained_translation =
      math::transform_point(prefix_inverse, target_world) -
      double3(evaluated.rotate_pivot_translate) - double3(evaluated.rotate_pivot);
  const double influence = std::clamp(constraint.influence, 0.0, 1.0);
  r_output.translation = math::interpolate(
      double3(evaluated.translation), constrained_translation, influence);
  for (int axis = 0; axis < 3; axis++) {
    r_output.translation_mask[axis] = !constraint.skip_translate[axis];
  }
  return true;
}

void BKE_maya_constraint_output_apply(Object &object,
                                      const MayaConstraintChannelOutput &output)
{
  bke::MayaObjectTransformRuntime &runtime = object.runtime->maya_transform;
  if (output.translation.has_value()) {
    for (int axis = 0; axis < 3; axis++) {
      if (output.translation_mask[axis]) {
        runtime.evaluated.translation[axis] = (*output.translation)[axis];
        runtime.translation_driven[axis] = true;
      }
    }
  }
  if (output.rotation.has_value()) {
    for (int axis = 0; axis < 3; axis++) {
      if (output.rotation_mask[axis]) {
        runtime.evaluated.rotation[axis] = (*output.rotation)[axis];
        runtime.rotation_driven[axis] = true;
      }
    }
  }
  if (output.scale.has_value()) {
    for (int axis = 0; axis < 3; axis++) {
      if (output.scale_mask[axis]) {
        runtime.evaluated.scale[axis] = (*output.scale)[axis];
        runtime.scale_driven[axis] = true;
      }
    }
  }
}

void BKE_object_eval_maya_channels_init(Depsgraph *depsgraph, Object *object)
{
  if (!BKE_object_uses_maya_transform(object)) {
    return;
  }
  bke::MayaObjectTransformRuntime &runtime = object->runtime->maya_transform;
  runtime.evaluated = *object->maya_transform;
  std::fill_n(runtime.translation_driven, 3, false);
  std::fill_n(runtime.rotation_driven, 3, false);
  std::fill_n(runtime.scale_driven, 3, false);
  runtime.valid = true;
  runtime.evaluation_version = DEG_get_update_count(depsgraph);
}

void BKE_object_maya_evaluated_channels_invalidate(Object &object)
{
  if (object.runtime == nullptr) {
    return;
  }
  object.runtime->maya_transform.valid = false;
  std::fill_n(object.runtime->maya_transform.translation_driven, 3, false);
  std::fill_n(object.runtime->maya_transform.rotation_driven, 3, false);
  std::fill_n(object.runtime->maya_transform.scale_driven, 3, false);
}

void BKE_object_eval_maya_local_transform(Depsgraph * /*depsgraph*/, Object *object)
{
  if (!BKE_object_uses_maya_transform(object)) {
    return;
  }
  if (!object->runtime->maya_transform.valid) {
    object->runtime->maya_transform.evaluated = *object->maya_transform;
    object->runtime->maya_transform.valid = true;
  }
  object->runtime->object_to_world = float4x4(BKE_maya_transform_dag_local_matrix(
      object->runtime->maya_transform.evaluated));
}

void BKE_object_eval_maya_constraints(Depsgraph *depsgraph,
                                      Scene * /*scene*/,
                                      Object *object)
{
  if (!BKE_object_uses_maya_transform(object) || object->maya_constraints.is_empty()) {
    return;
  }
  if (!object->runtime->maya_transform.valid) {
    BKE_object_eval_maya_channels_init(depsgraph, object);
  }
  const double4x4 parent_effect = maya_parent_effect_get(*object);
  const MayaConstraintEvalContext context{*object, parent_effect};
  for (const MayaConstraint &constraint : object->maya_constraints) {
    MayaConstraintChannelOutput output;
    bool evaluated = false;
    switch (constraint.type) {
      case MAYA_CONSTRAINT_POINT:
        evaluated = BKE_maya_point_constraint_evaluate(constraint, context, output);
        break;
      case MAYA_CONSTRAINT_ORIENT:
      case MAYA_CONSTRAINT_SCALE:
      case MAYA_CONSTRAINT_PARENT:
      case MAYA_CONSTRAINT_AIM:
        break;
    }
    if (evaluated) {
      BKE_maya_constraint_output_apply(*object, output);
    }
  }

  BKE_object_eval_maya_local_transform(depsgraph, object);
  if (object->parent != nullptr) {
    BKE_object_eval_parent(depsgraph, object);
  }
}

bool BKE_object_maya_channel_is_driven(const Object &object,
                                       const eMayaTransformChannel channel,
                                       const int axis)
{
  if (!BKE_object_uses_maya_transform(&object) || object.runtime == nullptr || axis < 0 ||
      axis > 2)
  {
    return false;
  }
  const bke::MayaObjectTransformRuntime &runtime = object.runtime->maya_transform;
  switch (channel) {
    case MAYA_TRANSFORM_CHANNEL_TRANSLATION:
      return runtime.translation_driven[axis];
    case MAYA_TRANSFORM_CHANNEL_ROTATION:
      return runtime.rotation_driven[axis];
    case MAYA_TRANSFORM_CHANNEL_SCALE:
      return runtime.scale_driven[axis];
  }
  return false;
}

}  // namespace blender
