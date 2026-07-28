/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include "DNA_object_types.h"

#include "BLI_math_euler_types.hh"
#include "BLI_math_matrix_types.hh"
#include "BLI_math_quaternion_types.hh"
#include "BLI_math_rotation.h"

namespace blender {

struct Object;

struct MayaTransformCapabilities {
  bool edit_pivot_position = false;
  bool edit_pivot_orientation = false;
  bool bake_position = false;
  bool bake_orientation = false;
  bool apply_translation = false;
  bool apply_rotation = false;
  bool apply_scale = false;
  bool preserve_children = false;
  bool geometry_compensation = false;
};

enum eMayaTransformSetPolicy {
  MAYA_TRANSFORM_SET_CHANNELS = 0,
  MAYA_TRANSFORM_SET_TRANSLATION_ONLY,
  MAYA_TRANSFORM_SET_ROTATION_ONLY,
  MAYA_TRANSFORM_SET_SCALE_ONLY,
  MAYA_TRANSFORM_SET_RESET_PIVOTS,
  MAYA_TRANSFORM_SET_BAKE_SPECIAL_CHANNELS,
};

struct MayaTransformSetOptions {
  eMayaTransformSetPolicy policy = MAYA_TRANSFORM_SET_CHANNELS;
  bool preserve_rotate_axis = true;
  bool preserve_pivots = true;
  bool preserve_offset_parent_matrix = true;
  bool use_compatible_euler = true;
};

struct MayaLinearDecomposition {
  double3 scale = double3(1.0);
  double3 shear = double3(0.0);
  double3 rotation = double3(0.0);
  bool valid = false;
};

MayaTransformCapabilities BKE_maya_transform_capabilities_get(const Object &object);

void BKE_maya_transform_set_defaults(MayaObjectTransform &transform);

eEulerRotationOrders BKE_maya_rotation_order_to_blender(eMayaRotationOrder order);
eMayaRotationOrder BKE_maya_rotation_order_from_blender(eEulerRotationOrders order);

math::QuaternionBase<double> BKE_maya_rotate_axis_quaternion(const MayaObjectTransform &transform);

double4x4 BKE_maya_transform_channel_matrix(const MayaObjectTransform &transform);
double3x3 BKE_maya_transform_rotation_matrix(const MayaObjectTransform &transform);
double4x4 BKE_maya_transform_dag_local_matrix(const MayaObjectTransform &transform);
double4x4 BKE_maya_transform_world_matrix(const MayaObjectTransform &transform,
                                          const double4x4 &parent_effect_matrix);

MayaLinearDecomposition BKE_maya_decompose_linear_compatible(const double3x3 &matrix,
                                                             const MayaObjectTransform &reference);
bool BKE_maya_matrix_orthonormalize(const double3x3 &matrix, float r_axis[3][3]);
bool BKE_maya_transform_set_rotation_matrix(MayaObjectTransform &transform,
                                            const double3x3 &rotation_matrix,
                                            bool use_compatible_euler);
bool BKE_maya_transform_set_channel_matrix(MayaObjectTransform &transform,
                                           const double4x4 &target_channel_matrix,
                                           const MayaTransformSetOptions &options);
bool BKE_object_maya_set_dag_local_matrix(Object &object,
                                          const double4x4 &target_dag_local,
                                          const MayaTransformSetOptions &options);
bool BKE_object_maya_set_world_matrix(Object &object,
                                      const double4x4 &parent_effect_matrix,
                                      const double4x4 &target_world,
                                      const MayaTransformSetOptions &options);

void BKE_maya_transform_set_rotate_pivot(MayaObjectTransform &transform,
                                         const double3 &new_pivot,
                                         bool preserve);
void BKE_maya_transform_set_scale_pivot(MayaObjectTransform &transform,
                                        const double3 &new_pivot,
                                        bool preserve);
bool BKE_maya_transform_set_rotation_order(MayaObjectTransform &transform,
                                           eMayaRotationOrder new_order,
                                           bool preserve);
bool BKE_maya_transform_set_rotate_axis(MayaObjectTransform &transform,
                                        const double3 &new_axis,
                                        bool preserve);

double3 BKE_object_maya_rotate_pivot_world_get(const Object &object,
                                               const double4x4 &parent_effect_matrix);
double3 BKE_object_maya_scale_pivot_world_get(const Object &object,
                                              const double4x4 &parent_effect_matrix);
double3 BKE_maya_rotate_pivot_world_get(const MayaObjectTransform &transform,
                                        const double4x4 &parent_effect_matrix);
double3 BKE_maya_scale_pivot_world_get(const MayaObjectTransform &transform,
                                       const double4x4 &parent_effect_matrix);
bool BKE_object_maya_rotate_pivot_world_set(Object &object,
                                            const double4x4 &parent_effect_matrix,
                                            const double3 &world_position,
                                            bool preserve);
bool BKE_object_maya_scale_pivot_world_set(Object &object,
                                           const double4x4 &parent_effect_matrix,
                                           const double3 &world_position,
                                           bool preserve);
bool BKE_object_maya_local_axis_world_get(const Object &object,
                                          const double4x4 &parent_effect_matrix,
                                          float r_axis[3][3]);
bool BKE_object_maya_parent_axis_world_get(const Object &object,
                                           const double4x4 &parent_effect_matrix,
                                           float r_axis[3][3]);
bool BKE_object_maya_gimbal_axis_world_get(const Object &object,
                                           const double4x4 &parent_effect_matrix,
                                           float r_axis[3][3]);

}  // namespace blender
