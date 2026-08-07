/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "BKE_object_custom_pivot.hh"

#include <algorithm>
#include <cmath>

#include "MEM_guardedalloc.h"

#include "DNA_object_types.h"

#include "BLI_math_matrix.hh"
#include "BLI_math_quaternion.hh"
#include "BLI_math_rotation.h"

#include "BKE_object.hh"
#include "BKE_object_transform_clarity.hh"
#include "BKE_object_types.hh"

namespace blender {

static bool object_world_orientation_get(const Object &object,
                                         math::QuaternionBase<double> &r_orientation)
{
  /* Share the orthonormalization policy of the Clarity transform axes. Deriving the basis differently
   * here would offset the pivot orientation from the axes the transform converter uses, and would
   * flip mirrored objects by 180 degrees relative to them. */
  float rotation[3][3];
  if (!BKE_clarity_matrix_orthonormalize(double3x3(double4x4(object.object_to_world())), rotation)) {
    return false;
  }
  float quaternion[4];
  mat3_to_quat(quaternion, rotation);
  r_orientation = math::normalize(math::QuaternionBase<double>(
      quaternion[0], quaternion[1], quaternion[2], quaternion[3]));
  return true;
}

ObjectCustomPivot *BKE_object_custom_pivot_ensure(Object &object)
{
  if (object.custom_pivot == nullptr) {
    object.custom_pivot = MEM_new<ObjectCustomPivot>(__func__);
  }
  return object.custom_pivot;
}

void BKE_object_custom_pivot_reset(Object &object)
{
  MEM_SAFE_DELETE(object.custom_pivot);
}

bool BKE_object_custom_pivot_position_valid(const Object &object, const bool use_scale_pivot)
{
  if (object.custom_pivot == nullptr) {
    return false;
  }
  return use_scale_pivot ? object.custom_pivot->scale_pivot_valid :
                           object.custom_pivot->rotate_pivot_valid;
}

bool BKE_object_custom_pivot_orientation_valid(const Object &object)
{
  return object.custom_pivot != nullptr && object.custom_pivot->orientation_valid;
}

/** Free the storage once no channel is authored anymore. */
static void object_custom_pivot_free_if_unused(Object &object)
{
  const ObjectCustomPivot &pivot = *object.custom_pivot;
  if (!pivot.rotate_pivot_valid && !pivot.scale_pivot_valid && !pivot.orientation_valid) {
    BKE_object_custom_pivot_reset(object);
  }
}

void BKE_object_custom_pivot_position_clear(Object &object,
                                            const bool clear_rotate_pivot,
                                            const bool clear_scale_pivot)
{
  if (object.custom_pivot == nullptr) {
    return;
  }
  if (clear_rotate_pivot) {
    object.custom_pivot->rotate_pivot_valid = 0;
    std::fill_n(object.custom_pivot->rotate_pivot, 3, 0.0);
  }
  if (clear_scale_pivot) {
    object.custom_pivot->scale_pivot_valid = 0;
    std::fill_n(object.custom_pivot->scale_pivot, 3, 0.0);
  }
  object_custom_pivot_free_if_unused(object);
}

void BKE_object_custom_pivot_orientation_clear(Object &object)
{
  if (object.custom_pivot == nullptr) {
    return;
  }
  object.custom_pivot->orientation_valid = 0;
  object.custom_pivot->orientation[0] = 1.0;
  std::fill_n(&object.custom_pivot->orientation[1], 3, 0.0);
  object_custom_pivot_free_if_unused(object);
}

bool BKE_object_custom_pivot_position_world_get(const Object &object,
                                                const bool use_scale_pivot,
                                                double3 &r_position)
{
  if (!BKE_object_custom_pivot_position_valid(object, use_scale_pivot)) {
    return false;
  }
  const double3 local_position(use_scale_pivot ? object.custom_pivot->scale_pivot :
                                                object.custom_pivot->rotate_pivot);
  r_position = math::transform_point(double4x4(object.object_to_world()), local_position);
  return true;
}

bool BKE_object_custom_pivot_position_world_set(Object &object,
                                                const bool use_scale_pivot,
                                                const double3 &position)
{
  bool success;
  const double4x4 world_inverse = math::invert(double4x4(object.object_to_world()), success);
  if (!success) {
    return false;
  }
  ObjectCustomPivot &pivot = *BKE_object_custom_pivot_ensure(object);
  const double3 local_position = math::transform_point(world_inverse, position);
  std::copy_n(static_cast<const double *>(local_position),
              3,
              use_scale_pivot ? pivot.scale_pivot : pivot.rotate_pivot);
  /* Only the written pivot becomes valid, the other one keeps its previous state. */
  if (use_scale_pivot) {
    pivot.scale_pivot_valid = true;
  }
  else {
    pivot.rotate_pivot_valid = true;
  }
  return true;
}

bool BKE_object_custom_pivot_orientation_world_get(
    const Object &object, math::QuaternionBase<double> &r_orientation)
{
  math::QuaternionBase<double> object_orientation;
  if (!object_world_orientation_get(object, object_orientation)) {
    return false;
  }
  if (object.custom_pivot == nullptr || !object.custom_pivot->orientation_valid) {
    r_orientation = object_orientation;
    return true;
  }
  /* Stored in world space, and read back as it was stored. Maya's is the same: the capture in
   * `tests/pivot_reference` rotates the object after aiming a frame at a component and
   * `manipPivot -q -ori` comes back numerically unchanged, so the frame does not follow the object.
   * Storing it object-local made it follow, which also meant every bake had to carry it over by
   * hand. */
  r_orientation = math::normalize(math::QuaternionBase<double>(object.custom_pivot->orientation[0],
                                                               object.custom_pivot->orientation[1],
                                                               object.custom_pivot->orientation[2],
                                                               object.custom_pivot->orientation[3]));
  return true;
}

bool BKE_object_custom_pivot_orientation_world_set(
    Object &object, const math::QuaternionBase<double> &orientation)
{
  const math::QuaternionBase<double> world_orientation = math::normalize(orientation);
  if (!std::isfinite(world_orientation.w) || !std::isfinite(world_orientation.x) ||
      !std::isfinite(world_orientation.y) || !std::isfinite(world_orientation.z))
  {
    return false;
  }
  ObjectCustomPivot &pivot = *BKE_object_custom_pivot_ensure(object);
  pivot.orientation[0] = world_orientation.w;
  pivot.orientation[1] = world_orientation.x;
  pivot.orientation[2] = world_orientation.y;
  pivot.orientation[3] = world_orientation.z;
  pivot.orientation_valid = true;
  return true;
}

/* -------------------------------------------------------------------- */
/** \name Object Pivot Resolver
 * \{ */

static bool object_pivot_uses_dag_channels(const Object &object)
{
  return BKE_object_uses_clarity_transform(&object);
}

static double4x4 object_parent_effect_matrix_get(const Object &object)
{
  if (object.parent == nullptr) {
    return double4x4::identity();
  }
  float parent_effect[4][4];
  BKE_object_get_parent_matrix(&object, object.parent, parent_effect);
  return double4x4(float4x4(parent_effect));
}

bool BKE_object_pivot_valid(const Object &object, const bool use_scale_pivot)
{
  if (object_pivot_uses_dag_channels(object)) {
    /* Reading only `rotate_pivot` reported "no custom pivot" for a transform whose pivot was
     * several units away from the origin, so the manipulator drew itself at the origin while every
     * rotation kept using the channels: a pivot that looked broken and could not be reset because
     * nothing admitted it existed. */
    const ClarityObjectTransform &transform = *object.clarity_transform;
    const double3 pivot(use_scale_pivot ? transform.scale_pivot : transform.rotate_pivot);
    const double3 pivot_translate(use_scale_pivot ? transform.scale_pivot_translate :
                                                    transform.rotate_pivot_translate);
    return pivot != double3(0.0) || pivot_translate != double3(0.0);
  }
  return BKE_object_custom_pivot_position_valid(object, use_scale_pivot);
}

bool BKE_object_pivot_world_get(const Object &object,
                                const bool use_scale_pivot,
                                double3 &r_position)
{
  if (object_pivot_uses_dag_channels(object)) {
    if (!BKE_object_pivot_valid(object, use_scale_pivot)) {
      return false;
    }
    const double4x4 parent_effect = object_parent_effect_matrix_get(object);
    r_position = use_scale_pivot ? BKE_object_clarity_scale_pivot_world_get(object, parent_effect) :
                                   BKE_object_clarity_rotate_pivot_world_get(object, parent_effect);
    return true;
  }
  return BKE_object_custom_pivot_position_world_get(object, use_scale_pivot, r_position);
}

double3 BKE_object_origin_display_position_get(const Object &object)
{
  double3 position;
  if (BKE_object_pivot_world_get(object, false, position) ||
      BKE_object_pivot_world_get(object, true, position))
  {
    return position;
  }
  return double3(object.object_to_world().location());
}

/** \} */

}  // namespace blender
