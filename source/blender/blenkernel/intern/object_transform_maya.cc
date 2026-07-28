/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup bke
 */

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>

#include "DNA_object_types.h"

#include "BLI_math_euler.hh"
#include "BLI_math_matrix.hh"
#include "BLI_math_matrix_types.hh"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.hh"
#include "BLI_utildefines.h"

#include "BKE_object.hh"
#include "BKE_maya_constraints.hh"
#include "BKE_object_transform_maya.hh"

namespace blender {

MayaTransformCapabilities BKE_maya_transform_capabilities_get(const Object &object)
{
  MayaTransformCapabilities capabilities;
  switch (object.type) {
    case OB_MESH:
      capabilities.edit_pivot_position = true;
      capabilities.edit_pivot_orientation = true;
      capabilities.bake_position = true;
      capabilities.bake_orientation = true;
      capabilities.apply_translation = true;
      capabilities.apply_rotation = true;
      capabilities.apply_scale = true;
      capabilities.preserve_children = true;
      capabilities.geometry_compensation = true;
      break;
    case OB_EMPTY:
    case OB_CAMERA:
    case OB_LAMP:
      capabilities.edit_pivot_position = true;
      capabilities.edit_pivot_orientation = true;
      capabilities.bake_position = true;
      capabilities.bake_orientation = true;
      capabilities.apply_translation = true;
      capabilities.apply_rotation = true;
      capabilities.apply_scale = true;
      capabilities.preserve_children = true;
      break;
    case OB_ARMATURE:
      capabilities.edit_pivot_position = true;
      capabilities.edit_pivot_orientation = true;
      break;
    case OB_CURVES_LEGACY:
    case OB_SURF:
    case OB_FONT:
    case OB_CURVES:
      capabilities.edit_pivot_position = true;
      capabilities.edit_pivot_orientation = true;
      capabilities.preserve_children = true;
      break;
    default:
      break;
  }
  return capabilities;
}

void BKE_maya_transform_set_defaults(MayaObjectTransform &transform)
{
  transform = MayaObjectTransform();
}

eEulerRotationOrders BKE_maya_rotation_order_to_blender(const eMayaRotationOrder order)
{
  switch (order) {
    case MAYA_ROT_ORDER_YZX:
      return EULER_ORDER_YZX;
    case MAYA_ROT_ORDER_ZXY:
      return EULER_ORDER_ZXY;
    case MAYA_ROT_ORDER_XZY:
      return EULER_ORDER_XZY;
    case MAYA_ROT_ORDER_YXZ:
      return EULER_ORDER_YXZ;
    case MAYA_ROT_ORDER_ZYX:
      return EULER_ORDER_ZYX;
    case MAYA_ROT_ORDER_XYZ:
    default:
      return EULER_ORDER_XYZ;
  }
}

eMayaRotationOrder BKE_maya_rotation_order_from_blender(const eEulerRotationOrders order)
{
  switch (order) {
    case EULER_ORDER_YZX:
      return MAYA_ROT_ORDER_YZX;
    case EULER_ORDER_ZXY:
      return MAYA_ROT_ORDER_ZXY;
    case EULER_ORDER_XZY:
      return MAYA_ROT_ORDER_XZY;
    case EULER_ORDER_YXZ:
      return MAYA_ROT_ORDER_YXZ;
    case EULER_ORDER_ZYX:
      return MAYA_ROT_ORDER_ZYX;
    case EULER_ORDER_XYZ:
    default:
      return MAYA_ROT_ORDER_XYZ;
  }
}

static double4x4 translation_matrix(const double translation[3])
{
  double4x4 matrix = double4x4::identity();
  matrix[3][0] = translation[0];
  matrix[3][1] = translation[1];
  matrix[3][2] = translation[2];
  return matrix;
}

static double4x4 translation_matrix_negated(const double translation[3])
{
  double4x4 matrix = double4x4::identity();
  matrix[3][0] = -translation[0];
  matrix[3][1] = -translation[1];
  matrix[3][2] = -translation[2];
  return matrix;
}

static double4x4 scale_matrix(const double scale[3])
{
  double4x4 matrix = double4x4::identity();
  matrix[0][0] = scale[0];
  matrix[1][1] = scale[1];
  matrix[2][2] = scale[2];
  return matrix;
}

static double4x4 shear_matrix(const double shear[3])
{
  double4x4 matrix = double4x4::identity();
  matrix[1][0] = shear[0];
  matrix[2][0] = shear[1];
  matrix[2][1] = shear[2];
  return matrix;
}

static double4x4 axis_rotation_matrix(const int axis, const double angle)
{
  const double cosine = std::cos(angle);
  const double sine = std::sin(angle);
  double4x4 matrix = double4x4::identity();

  switch (axis) {
    case 0:
      matrix[1][1] = cosine;
      matrix[2][1] = -sine;
      matrix[1][2] = sine;
      matrix[2][2] = cosine;
      break;
    case 1:
      matrix[0][0] = cosine;
      matrix[2][0] = sine;
      matrix[0][2] = -sine;
      matrix[2][2] = cosine;
      break;
    case 2:
      matrix[0][0] = cosine;
      matrix[1][0] = -sine;
      matrix[0][1] = sine;
      matrix[1][1] = cosine;
      break;
  }
  return matrix;
}

static double4x4 euler_rotation_matrix(const double rotation[3],
                                       const eMayaRotationOrder rotation_order)
{
  int axes[3];
  switch (rotation_order) {
    case MAYA_ROT_ORDER_YZX:
      axes[0] = 1;
      axes[1] = 2;
      axes[2] = 0;
      break;
    case MAYA_ROT_ORDER_ZXY:
      axes[0] = 2;
      axes[1] = 0;
      axes[2] = 1;
      break;
    case MAYA_ROT_ORDER_XZY:
      axes[0] = 0;
      axes[1] = 2;
      axes[2] = 1;
      break;
    case MAYA_ROT_ORDER_YXZ:
      axes[0] = 1;
      axes[1] = 0;
      axes[2] = 2;
      break;
    case MAYA_ROT_ORDER_ZYX:
      axes[0] = 2;
      axes[1] = 1;
      axes[2] = 0;
      break;
    case MAYA_ROT_ORDER_XYZ:
    default:
      axes[0] = 0;
      axes[1] = 1;
      axes[2] = 2;
      break;
  }

  double4x4 matrix = double4x4::identity();
  for (const int axis : axes) {
    matrix = axis_rotation_matrix(axis, rotation[axis]) * matrix;
  }
  return matrix;
}

math::QuaternionBase<double> BKE_maya_rotate_axis_quaternion(const MayaObjectTransform &transform)
{
  return math::to_quaternion(math::EulerXYZBase<double>(double3(transform.rotate_axis)));
}

static double4x4 rotate_axis_matrix(const MayaObjectTransform &transform)
{
  return math::from_rotation<double4x4>(BKE_maya_rotate_axis_quaternion(transform));
}

static bool matrix_is_finite(const double4x4 &matrix)
{
  for (int index = 0; index < 16; index++) {
    if (!std::isfinite(matrix.base_ptr()[index])) {
      return false;
    }
  }
  return true;
}

double4x4 BKE_maya_transform_channel_matrix(const MayaObjectTransform &transform)
{
  const double4x4 scale_pivot = translation_matrix(transform.scale_pivot);
  const double4x4 rotate_pivot = translation_matrix(transform.rotate_pivot);

  return translation_matrix(transform.translation) *
         translation_matrix(transform.rotate_pivot_translate) * rotate_pivot *
         euler_rotation_matrix(transform.rotation, transform.rotation_order) *
         rotate_axis_matrix(transform) * translation_matrix_negated(transform.rotate_pivot) *
         translation_matrix(transform.scale_pivot_translate) * scale_pivot *
         shear_matrix(transform.shear) * scale_matrix(transform.scale) *
         translation_matrix_negated(transform.scale_pivot);
}

double3x3 BKE_maya_transform_rotation_matrix(const MayaObjectTransform &transform)
{
  return double3x3(euler_rotation_matrix(transform.rotation, transform.rotation_order));
}

double4x4 BKE_maya_transform_dag_local_matrix(const MayaObjectTransform &transform)
{
  return double4x4(transform.offset_parent_matrix) * BKE_maya_transform_channel_matrix(transform);
}

double4x4 BKE_maya_transform_world_matrix(const MayaObjectTransform &transform,
                                          const double4x4 &parent_effect_matrix)
{
  const double4x4 dag_local_matrix = BKE_maya_transform_dag_local_matrix(transform);
  return transform.inherits_transform ? parent_effect_matrix * dag_local_matrix : dag_local_matrix;
}

void BKE_maya_transform_set_rotate_pivot(MayaObjectTransform &transform,
                                         const double3 &new_pivot,
                                         const bool preserve)
{
  if (preserve) {
    const double3 pivot_delta = double3(transform.rotate_pivot) - new_pivot;
    const double3x3 rotation = double3x3(
        euler_rotation_matrix(transform.rotation, transform.rotation_order) *
        rotate_axis_matrix(transform));
    const double3 compensation = pivot_delta - rotation * pivot_delta;
    for (int axis = 0; axis < 3; axis++) {
      transform.rotate_pivot_translate[axis] += compensation[axis];
    }
  }
  for (int axis = 0; axis < 3; axis++) {
    transform.rotate_pivot[axis] = new_pivot[axis];
  }
}

void BKE_maya_transform_set_scale_pivot(MayaObjectTransform &transform,
                                        const double3 &new_pivot,
                                        const bool preserve)
{
  if (preserve) {
    const double3 pivot_delta = double3(transform.scale_pivot) - new_pivot;
    const double3x3 scale_shear = double3x3(shear_matrix(transform.shear) *
                                            scale_matrix(transform.scale));
    const double3 compensation = pivot_delta - scale_shear * pivot_delta;
    for (int axis = 0; axis < 3; axis++) {
      transform.scale_pivot_translate[axis] += compensation[axis];
    }
  }
  for (int axis = 0; axis < 3; axis++) {
    transform.scale_pivot[axis] = new_pivot[axis];
  }
}

static math::EulerOrder maya_math_rotation_order(const eMayaRotationOrder order)
{
  switch (BKE_maya_rotation_order_to_blender(order)) {
    case EULER_ORDER_XZY:
      return math::EulerOrder::XZY;
    case EULER_ORDER_YXZ:
      return math::EulerOrder::YXZ;
    case EULER_ORDER_YZX:
      return math::EulerOrder::YZX;
    case EULER_ORDER_ZXY:
      return math::EulerOrder::ZXY;
    case EULER_ORDER_ZYX:
      return math::EulerOrder::ZYX;
    case EULER_ORDER_XYZ:
    default:
      return math::EulerOrder::XYZ;
  }
}

static bool set_rotation_from_matrix(MayaObjectTransform &transform,
                                     const double3x3 &rotation_matrix,
                                     const eMayaRotationOrder order,
                                     const bool use_compatible_euler)
{
  const math::Euler3Base<double> reference(double3(transform.rotation),
                                           maya_math_rotation_order(order));
  const math::Euler3Base<double> euler = use_compatible_euler ?
                                             math::to_nearest_euler(rotation_matrix, reference) :
                                             math::to_euler(rotation_matrix,
                                                            maya_math_rotation_order(order));
  const double3 rotation(euler);
  if (!std::isfinite(rotation.x) || !std::isfinite(rotation.y) || !std::isfinite(rotation.z)) {
    return false;
  }
  for (int axis = 0; axis < 3; axis++) {
    transform.rotation[axis] = rotation[axis];
  }
  return true;
}

bool BKE_maya_transform_set_rotation_matrix(MayaObjectTransform &transform,
                                            const double3x3 &rotation_matrix,
                                            const bool use_compatible_euler)
{
  return set_rotation_from_matrix(
      transform, rotation_matrix, transform.rotation_order, use_compatible_euler);
}

static bool qr_decompose(const double3x3 &matrix, double3x3 &r_rotation, double3x3 &r_upper)
{
  constexpr double singular_epsilon = 1.0e-12;

  double3 axis_x = matrix[0];
  const double scale_x = math::length(axis_x);
  if (!(scale_x > singular_epsilon)) {
    return false;
  }
  axis_x /= scale_x;

  const double upper_xy = math::dot(axis_x, matrix[1]);
  double3 axis_y = matrix[1] - axis_x * upper_xy;
  const double scale_y = math::length(axis_y);
  if (!(scale_y > singular_epsilon)) {
    return false;
  }
  axis_y /= scale_y;

  const double upper_xz = math::dot(axis_x, matrix[2]);
  const double upper_yz = math::dot(axis_y, matrix[2]);
  double3 axis_z = matrix[2] - axis_x * upper_xz - axis_y * upper_yz;
  const double scale_z = math::length(axis_z);
  if (!(scale_z > singular_epsilon)) {
    return false;
  }
  axis_z /= scale_z;

  r_rotation = double3x3::identity();
  r_rotation[0] = axis_x;
  r_rotation[1] = axis_y;
  r_rotation[2] = axis_z;

  r_upper = double3x3::zero();
  r_upper[0][0] = scale_x;
  r_upper[1][0] = upper_xy;
  r_upper[2][0] = upper_xz;
  r_upper[1][1] = scale_y;
  r_upper[2][1] = upper_yz;
  r_upper[2][2] = scale_z;
  return true;
}

static double scale_compatibility_score(const double3 &scale, const MayaObjectTransform &reference)
{
  double score = 0.0;
  for (int axis = 0; axis < 3; axis++) {
    score += std::abs(scale[axis] - reference.scale[axis]) /
             (1.0 + std::abs(reference.scale[axis]));
  }
  return score;
}

MayaLinearDecomposition BKE_maya_decompose_linear_compatible(const double3x3 &matrix,
                                                             const MayaObjectTransform &reference)
{
  MayaLinearDecomposition result;
  double3x3 base_rotation;
  double3x3 upper;
  if (!qr_decompose(matrix, base_rotation, upper)) {
    return result;
  }

  const double4x4 rotate_axis_4x4 = rotate_axis_matrix(reference);
  const double3x3 rotate_axis = double3x3(rotate_axis_4x4);
  double best_score = std::numeric_limits<double>::infinity();

  for (const std::array<double, 3> signs : {std::array<double, 3>{1.0, 1.0, 1.0},
                                            {1.0, -1.0, -1.0},
                                            {-1.0, 1.0, -1.0},
                                            {-1.0, -1.0, 1.0},
                                            {-1.0, -1.0, -1.0},
                                            {-1.0, 1.0, 1.0},
                                            {1.0, -1.0, 1.0},
                                            {1.0, 1.0, -1.0}})
  {
    double3x3 signed_rotation = base_rotation;
    for (int axis = 0; axis < 3; axis++) {
      signed_rotation[axis] *= signs[axis];
    }
    if (math::determinant(signed_rotation) <= 0.0) {
      continue;
    }

    const double3 scale = {signs[0] * upper[0][0], signs[1] * upper[1][1], signs[2] * upper[2][2]};
    if (std::abs(scale.x) <= 1.0e-12 || std::abs(scale.y) <= 1.0e-12 ||
        std::abs(scale.z) <= 1.0e-12)
    {
      continue;
    }

    const double3 shear = {signs[0] * upper[1][0] / scale.y,
                           signs[0] * upper[2][0] / scale.z,
                           signs[1] * upper[2][1] / scale.z};
    MayaObjectTransform candidate = reference;
    const double3x3 channel_rotation = signed_rotation * math::transpose(rotate_axis);
    if (!set_rotation_from_matrix(candidate, channel_rotation, candidate.rotation_order, true)) {
      continue;
    }

    double score = scale_compatibility_score(scale, reference);
    for (int axis = 0; axis < 3; axis++) {
      score += 1.0e-9 * std::abs(candidate.rotation[axis] - reference.rotation[axis]);
    }
    if (score < best_score) {
      best_score = score;
      result.scale = scale;
      result.shear = shear;
      result.rotation = double3(candidate.rotation);
      result.valid = true;
    }
  }
  return result;
}

static void zero_special_pivots(MayaObjectTransform &transform)
{
  for (int axis = 0; axis < 3; axis++) {
    transform.rotate_pivot[axis] = 0.0;
    transform.rotate_pivot_translate[axis] = 0.0;
    transform.scale_pivot[axis] = 0.0;
    transform.scale_pivot_translate[axis] = 0.0;
  }
}

static void zero_rotate_axis(MayaObjectTransform &transform)
{
  for (double &value : transform.rotate_axis) {
    value = 0.0;
  }
}

bool BKE_maya_transform_set_channel_matrix(MayaObjectTransform &transform,
                                           const double4x4 &target_channel_matrix,
                                           const MayaTransformSetOptions &options)
{
  if (!matrix_is_finite(target_channel_matrix)) {
    return false;
  }

  MayaObjectTransform result = transform;
  if (!options.preserve_pivots || ELEM(options.policy,
                                       MAYA_TRANSFORM_SET_RESET_PIVOTS,
                                       MAYA_TRANSFORM_SET_BAKE_SPECIAL_CHANNELS))
  {
    zero_special_pivots(result);
  }
  if (!options.preserve_rotate_axis || options.policy == MAYA_TRANSFORM_SET_BAKE_SPECIAL_CHANNELS)
  {
    zero_rotate_axis(result);
  }

  if (options.policy != MAYA_TRANSFORM_SET_TRANSLATION_ONLY) {
    const MayaLinearDecomposition decomposition = BKE_maya_decompose_linear_compatible(
        double3x3(target_channel_matrix), result);
    if (!decomposition.valid) {
      return false;
    }

    if (options.policy != MAYA_TRANSFORM_SET_SCALE_ONLY) {
      for (int axis = 0; axis < 3; axis++) {
        result.rotation[axis] = decomposition.rotation[axis];
      }
    }
    if (ELEM(options.policy,
             MAYA_TRANSFORM_SET_CHANNELS,
             MAYA_TRANSFORM_SET_RESET_PIVOTS,
             MAYA_TRANSFORM_SET_BAKE_SPECIAL_CHANNELS))
    {
      for (int axis = 0; axis < 3; axis++) {
        result.shear[axis] = decomposition.shear[axis];
      }
    }
    if (options.policy != MAYA_TRANSFORM_SET_ROTATION_ONLY) {
      for (int axis = 0; axis < 3; axis++) {
        result.scale[axis] = decomposition.scale[axis];
      }
    }

    if (!options.use_compatible_euler && options.policy != MAYA_TRANSFORM_SET_SCALE_ONLY) {
      const double3x3 rotate_axis = double3x3(rotate_axis_matrix(result));
      double3x3 rotation_and_axis = double3x3(target_channel_matrix);
      const double3x3 shear_and_scale = double3x3(shear_matrix(result.shear) *
                                                  scale_matrix(result.scale));
      bool inverse_success;
      const double3x3 inverse_scale_shear = math::invert(shear_and_scale, inverse_success);
      if (!inverse_success) {
        return false;
      }
      rotation_and_axis = rotation_and_axis * inverse_scale_shear;
      if (!set_rotation_from_matrix(result,
                                    rotation_and_axis * math::transpose(rotate_axis),
                                    result.rotation_order,
                                    false))
      {
        return false;
      }
    }
  }

  if (ELEM(options.policy,
           MAYA_TRANSFORM_SET_CHANNELS,
           MAYA_TRANSFORM_SET_TRANSLATION_ONLY,
           MAYA_TRANSFORM_SET_RESET_PIVOTS,
           MAYA_TRANSFORM_SET_BAKE_SPECIAL_CHANNELS))
  {
    MayaObjectTransform without_translation = result;
    for (double &value : without_translation.translation) {
      value = 0.0;
    }
    const double3 translation = target_channel_matrix.location() -
                                BKE_maya_transform_channel_matrix(without_translation).location();
    for (int axis = 0; axis < 3; axis++) {
      result.translation[axis] = translation[axis];
    }
  }

  transform = result;
  return true;
}

static void offset_parent_matrix_set(MayaObjectTransform &transform, const double4x4 &matrix)
{
  std::copy_n(matrix.base_ptr(), 16, &transform.offset_parent_matrix[0][0]);
}

bool BKE_object_maya_set_dag_local_matrix(Object &object,
                                          const double4x4 &target_dag_local,
                                          const MayaTransformSetOptions &options)
{
  if (!BKE_object_uses_maya_transform(&object) || !matrix_is_finite(target_dag_local)) {
    return false;
  }

  MayaObjectTransform result = *object.maya_transform;
  double4x4 target_channel = target_dag_local;
  const bool preserve_offset_parent_matrix = options.preserve_offset_parent_matrix &&
                                             options.policy !=
                                                 MAYA_TRANSFORM_SET_BAKE_SPECIAL_CHANNELS;
  if (preserve_offset_parent_matrix) {
    bool inverse_success;
    const double4x4 offset_inverse = math::invert(double4x4(result.offset_parent_matrix),
                                                  inverse_success);
    if (!inverse_success) {
      return false;
    }
    target_channel = offset_inverse * target_dag_local;
  }
  else {
    offset_parent_matrix_set(result, double4x4::identity());
  }

  if (!BKE_maya_transform_set_channel_matrix(result, target_channel, options)) {
    return false;
  }
  *object.maya_transform = result;
  BKE_object_maya_evaluated_channels_invalidate(object);
  return true;
}

bool BKE_object_maya_set_world_matrix(Object &object,
                                      const double4x4 &parent_effect_matrix,
                                      const double4x4 &target_world,
                                      const MayaTransformSetOptions &options)
{
  if (!BKE_object_uses_maya_transform(&object) || !matrix_is_finite(target_world)) {
    return false;
  }

  double4x4 target_dag_local = target_world;
  if (object.maya_transform->inherits_transform) {
    bool inverse_success;
    const double4x4 parent_inverse = math::invert(parent_effect_matrix, inverse_success);
    if (!inverse_success) {
      return false;
    }
    target_dag_local = parent_inverse * target_world;
  }
  return BKE_object_maya_set_dag_local_matrix(object, target_dag_local, options);
}

bool BKE_maya_transform_set_rotation_order(MayaObjectTransform &transform,
                                           const eMayaRotationOrder new_order,
                                           const bool preserve)
{
  if (new_order < MAYA_ROT_ORDER_XYZ || new_order > MAYA_ROT_ORDER_ZYX) {
    return false;
  }
  if (new_order == transform.rotation_order) {
    return true;
  }
  if (!preserve) {
    transform.rotation_order = new_order;
    return true;
  }

  const double3x3 old_rotation(
      euler_rotation_matrix(transform.rotation, transform.rotation_order));
  if (!set_rotation_from_matrix(transform, old_rotation, new_order, true)) {
    return false;
  }
  transform.rotation_order = new_order;
  return true;
}

bool BKE_maya_transform_set_rotate_axis(MayaObjectTransform &transform,
                                        const double3 &new_axis,
                                        const bool preserve)
{
  if (preserve) {
    const double3x3 old_rotation(
        euler_rotation_matrix(transform.rotation, transform.rotation_order));
    const double3x3 old_rotate_axis(rotate_axis_matrix(transform));

    MayaObjectTransform new_axis_transform = transform;
    for (int axis = 0; axis < 3; axis++) {
      new_axis_transform.rotate_axis[axis] = new_axis[axis];
    }
    const double3x3 new_rotate_axis(rotate_axis_matrix(new_axis_transform));
    const double3x3 new_rotation = old_rotation * old_rotate_axis *
                                   math::transpose(new_rotate_axis);
    if (!set_rotation_from_matrix(transform, new_rotation, transform.rotation_order, true)) {
      return false;
    }
  }
  for (int axis = 0; axis < 3; axis++) {
    transform.rotate_axis[axis] = new_axis[axis];
  }
  return true;
}

static double4x4 maya_parent_offset_prefix(const MayaObjectTransform &transform,
                                           const double4x4 &parent_effect_matrix)
{
  const double4x4 offset_parent_matrix(transform.offset_parent_matrix);
  return transform.inherits_transform ? parent_effect_matrix * offset_parent_matrix :
                                        offset_parent_matrix;
}

double3 BKE_maya_rotate_pivot_world_get(const MayaObjectTransform &transform,
                                        const double4x4 &parent_effect_matrix)
{
  const double4x4 prefix = maya_parent_offset_prefix(transform, parent_effect_matrix) *
                           translation_matrix(transform.translation) *
                           translation_matrix(transform.rotate_pivot_translate) *
                           translation_matrix(transform.rotate_pivot);
  return prefix.location();
}

double3 BKE_maya_scale_pivot_world_get(const MayaObjectTransform &transform,
                                       const double4x4 &parent_effect_matrix)
{
  const double4x4 prefix = maya_parent_offset_prefix(transform, parent_effect_matrix) *
                           translation_matrix(transform.translation) *
                           translation_matrix(transform.rotate_pivot_translate) *
                           translation_matrix(transform.rotate_pivot) *
                           euler_rotation_matrix(transform.rotation, transform.rotation_order) *
                           rotate_axis_matrix(transform) *
                           translation_matrix_negated(transform.rotate_pivot) *
                           translation_matrix(transform.scale_pivot_translate) *
                           translation_matrix(transform.scale_pivot);
  return prefix.location();
}

double3 BKE_object_maya_rotate_pivot_world_get(const Object &object,
                                               const double4x4 &parent_effect_matrix)
{
  BLI_assert(BKE_object_uses_maya_transform(&object));
  return BKE_maya_rotate_pivot_world_get(*object.maya_transform, parent_effect_matrix);
}

double3 BKE_object_maya_scale_pivot_world_get(const Object &object,
                                              const double4x4 &parent_effect_matrix)
{
  BLI_assert(BKE_object_uses_maya_transform(&object));
  return BKE_maya_scale_pivot_world_get(*object.maya_transform, parent_effect_matrix);
}

static bool position_is_finite(const double3 &position)
{
  return std::isfinite(position.x) && std::isfinite(position.y) && std::isfinite(position.z);
}

bool BKE_object_maya_rotate_pivot_world_set(Object &object,
                                            const double4x4 &parent_effect_matrix,
                                            const double3 &world_position,
                                            const bool preserve)
{
  if (!BKE_object_uses_maya_transform(&object) || !position_is_finite(world_position)) {
    return false;
  }

  MayaObjectTransform result = *object.maya_transform;
  const double4x4 position_prefix = maya_parent_offset_prefix(result, parent_effect_matrix) *
                                    translation_matrix(result.translation);
  bool prefix_inverse_success;
  const double4x4 prefix_inverse = math::invert(position_prefix, prefix_inverse_success);
  if (!prefix_inverse_success) {
    return false;
  }
  const double3 target_in_translation_space = math::transform_point(prefix_inverse,
                                                                    world_position);

  double3 new_pivot = target_in_translation_space -
                      double3(result.rotate_pivot_translate);
  if (preserve) {
    const double3 old_pivot(result.rotate_pivot);
    const double3x3 rotation = double3x3(
        euler_rotation_matrix(result.rotation, result.rotation_order) *
        rotate_axis_matrix(result));
    bool rotation_inverse_success;
    const double3x3 rotation_inverse = math::invert(rotation, rotation_inverse_success);
    if (!rotation_inverse_success) {
      return false;
    }
    new_pivot = old_pivot +
                rotation_inverse *
                    (target_in_translation_space -
                     double3(result.rotate_pivot_translate) - old_pivot);
  }

  BKE_maya_transform_set_rotate_pivot(result, new_pivot, preserve);
  *object.maya_transform = result;
  BKE_object_maya_evaluated_channels_invalidate(object);
  return true;
}

bool BKE_object_maya_scale_pivot_world_set(Object &object,
                                           const double4x4 &parent_effect_matrix,
                                           const double3 &world_position,
                                           const bool preserve)
{
  if (!BKE_object_uses_maya_transform(&object) || !position_is_finite(world_position)) {
    return false;
  }

  MayaObjectTransform result = *object.maya_transform;
  const double4x4 position_prefix =
      maya_parent_offset_prefix(result, parent_effect_matrix) *
      translation_matrix(result.translation) *
      translation_matrix(result.rotate_pivot_translate) *
      translation_matrix(result.rotate_pivot) *
      euler_rotation_matrix(result.rotation, result.rotation_order) *
      rotate_axis_matrix(result) * translation_matrix_negated(result.rotate_pivot);
  bool prefix_inverse_success;
  const double4x4 prefix_inverse = math::invert(position_prefix, prefix_inverse_success);
  if (!prefix_inverse_success) {
    return false;
  }
  const double3 target_in_scale_space = math::transform_point(prefix_inverse, world_position);

  double3 new_pivot = target_in_scale_space - double3(result.scale_pivot_translate);
  if (preserve) {
    const double3 old_pivot(result.scale_pivot);
    const double3x3 scale_shear = double3x3(shear_matrix(result.shear) *
                                            scale_matrix(result.scale));
    bool scale_shear_inverse_success;
    const double3x3 scale_shear_inverse = math::invert(scale_shear,
                                                       scale_shear_inverse_success);
    if (!scale_shear_inverse_success) {
      return false;
    }
    new_pivot = old_pivot +
                scale_shear_inverse *
                    (target_in_scale_space - double3(result.scale_pivot_translate) - old_pivot);
  }

  BKE_maya_transform_set_scale_pivot(result, new_pivot, preserve);
  *object.maya_transform = result;
  BKE_object_maya_evaluated_channels_invalidate(object);
  return true;
}

static bool orthonormalize_matrix(const double3x3 &matrix, float r_axis[3][3])
{
  double3x3 rotation;
  double3x3 upper;
  if (!qr_decompose(matrix, rotation, upper)) {
    return false;
  }
  if (math::determinant(rotation) < 0.0) {
    rotation[2] = -rotation[2];
  }
  for (int column = 0; column < 3; column++) {
    for (int row = 0; row < 3; row++) {
      r_axis[column][row] = float(rotation[column][row]);
    }
  }
  return true;
}

bool BKE_maya_matrix_orthonormalize(const double3x3 &matrix, float r_axis[3][3])
{
  return orthonormalize_matrix(matrix, r_axis);
}

bool BKE_object_maya_local_axis_world_get(const Object &object,
                                          const double4x4 &parent_effect_matrix,
                                          float r_axis[3][3])
{
  if (!BKE_object_uses_maya_transform(&object)) {
    return false;
  }
  const MayaObjectTransform &transform = *object.maya_transform;
  const double3x3 axis = double3x3(
      maya_parent_offset_prefix(transform, parent_effect_matrix) *
      euler_rotation_matrix(transform.rotation, transform.rotation_order) *
      rotate_axis_matrix(transform));
  return orthonormalize_matrix(axis, r_axis);
}

bool BKE_object_maya_parent_axis_world_get(const Object &object,
                                           const double4x4 &parent_effect_matrix,
                                           float r_axis[3][3])
{
  if (!BKE_object_uses_maya_transform(&object)) {
    return false;
  }
  return orthonormalize_matrix(
      double3x3(maya_parent_offset_prefix(*object.maya_transform, parent_effect_matrix)), r_axis);
}

bool BKE_object_maya_gimbal_axis_world_get(const Object &object,
                                           const double4x4 &parent_effect_matrix,
                                           float r_axis[3][3])
{
  if (!BKE_object_uses_maya_transform(&object)) {
    return false;
  }

  const MayaObjectTransform &transform = *object.maya_transform;
  float rotation[3];
  for (int axis = 0; axis < 3; axis++) {
    rotation[axis] = float(transform.rotation[axis]);
  }
  float gimbal[3][3];
  eulO_to_gimbal_axis(
      gimbal, rotation, BKE_maya_rotation_order_to_blender(transform.rotation_order));
  const double3x3 world_gimbal = double3x3(
                                     maya_parent_offset_prefix(transform, parent_effect_matrix)) *
                                 double3x3(float3x3(gimbal)) *
                                 double3x3(rotate_axis_matrix(transform));
  return orthonormalize_matrix(world_gimbal, r_axis);
}

}  // namespace blender
