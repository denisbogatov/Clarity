/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup spview3d
 */

#include "ED_view3d_navigation.hh"

#include "BLI_math_vector.h"
#include "BLI_listbase.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_userdef_types.h"
#include "DNA_view3d_types.h"

#include "BKE_global.hh"
#include "BKE_main.hh"

#include "ED_view3d.hh"

#include "WM_types.hh"
#include "wm_event_types.hh"

#include "view3d_navigate.hh"

namespace blender::ed::view3d {

class BlenderNavigationSession final : public NavigationSession {
 private:
  ViewOpsData *vod_ = nullptr;
  const ViewOpsType *type_ = nullptr;
  bool invert_direction_ = false;

  const ListBaseT<ARegion> *view_region_list() const
  {
    if (vod_ == nullptr || G_MAIN == nullptr) {
      return nullptr;
    }
    for (const bScreen &screen : G_MAIN->screens) {
      if (BLI_findindex(&screen.areabase, vod_->area) != -1) {
        const SpaceLink *view_space = reinterpret_cast<const SpaceLink *>(vod_->v3d);
        for (const SpaceLink &space : vod_->area->spacedata) {
          if (&space == view_space) {
            const ListBaseT<ARegion> &regions = (&space == vod_->area->spacedata.first) ?
                                                   vod_->area->regionbase :
                                                   space.regionbase;
            if (BLI_findindex(&regions, vod_->region) != -1 &&
                vod_->region->regiondata == vod_->rv3d)
            {
              return &regions;
            }
            return nullptr;
          }
        }
        return nullptr;
      }
    }
    return nullptr;
  }

  bool restore_initial_state()
  {
    const ListBaseT<ARegion> *regions = view_region_list();
    if (regions == nullptr) {
      return false;
    }
    if (regions == &vod_->area->regionbase) {
      vod_->state_restore();
      return true;
    }

    ScrArea area_proxy{};
    area_proxy.regionbase = *regions;
    ScrArea *area = vod_->area;
    vod_->area = &area_proxy;
    vod_->state_restore();
    vod_->area = area;
    return true;
  }

  void abandon()
  {
    delete vod_;
    vod_ = nullptr;
    type_ = nullptr;
  }

  void finish(bContext *C)
  {
    viewops_data_free(C, vod_);
    vod_ = nullptr;
    type_ = nullptr;
  }

 public:
  BlenderNavigationSession(ViewOpsData *vod,
                           const ViewOpsType *type,
                           const bool invert_direction)
      : vod_(vod), type_(type), invert_direction_(invert_direction)
  {
  }

  ~BlenderNavigationSession() override
  {
    if (vod_ != nullptr) {
      if (restore_initial_state()) {
        finish(nullptr);
      }
      else {
        abandon();
      }
    }
  }

  NavigationResult update(bContext *C,
                          const int2 &mouse_xy,
                          const int2 & /*mouse_region_xy*/) override
  {
    if (vod_ == nullptr || type_ == nullptr || type_->apply_fn == nullptr) {
      return NavigationResult::Failed;
    }

    int2 apply_mouse = mouse_xy;
    if (invert_direction_) {
      apply_mouse = int2(vod_->init.event_xy) * 2 - mouse_xy;
    }

    const wmOperatorStatus result = type_->apply_fn(C, vod_, VIEW_APPLY, apply_mouse);
    if (result & OPERATOR_RUNNING_MODAL) {
      return NavigationResult::Running;
    }

    const NavigationResult navigation_result = (result & OPERATOR_FINISHED) ?
                                                   NavigationResult::Finished :
                                                   NavigationResult::Cancelled;
    finish(C);
    return navigation_result;
  }

  void confirm(bContext *C) override
  {
    if (vod_ == nullptr) {
      return;
    }
    type_->apply_fn(C, vod_, VIEW_CONFIRM, vod_->prev.event_xy);
    finish(C);
  }

  void cancel(bContext *C) override
  {
    if (vod_ == nullptr) {
      return;
    }
    const ListBaseT<ARegion> *regions = view_region_list();
    if (regions == nullptr) {
      abandon();
      return;
    }
    if (regions == &vod_->area->regionbase) {
      type_->apply_fn(C, vod_, VIEW_CANCEL, vod_->prev.event_xy);
    }
    else {
      restore_initial_state();
    }
    finish(C);
  }
};

static const ViewOpsType *navigation_type_from_mode(const NavigationMode mode)
{
  switch (mode) {
    case NavigationMode::Orbit:
      return &ViewOpsType_rotate;
    case NavigationMode::Pan:
      return &ViewOpsType_move;
    case NavigationMode::Dolly:
      return &ViewOpsType_zoom;
  }
  return nullptr;
}

std::unique_ptr<NavigationSession> navigation_session_begin(
    bContext *C, const NavigationBeginParams &params)
{
  const ViewOpsType *type = navigation_type_from_mode(params.mode);
  if (type == nullptr || type->apply_fn == nullptr ||
      (type->poll_fn != nullptr && !type->poll_fn(C)))
  {
    return nullptr;
  }

  wmEvent event{};
  event.type = LEFTMOUSE;
  event.val = KM_PRESS;
  copy_v2_v2_int(event.xy, params.mouse_xy);
  copy_v2_v2_int(event.prev_xy, params.mouse_xy);
  copy_v2_v2_int(event.mval, params.mouse_region_xy);

  ViewOpsData *vod = viewops_data_create(C, &event, type, params.use_mouse_position);
  if (vod == nullptr) {
    return nullptr;
  }

  ED_view3d_smooth_view_force_finish(C, vod->v3d, vod->region);

  if (type == &ViewOpsType_rotate && vod->use_dyn_ofs && !vod->rv3d->is_persp) {
    vod->use_dyn_ofs_ortho_correction = true;
  }
  if (type == &ViewOpsType_zoom && U.viewzoom == USER_ZOOM_CONTINUE) {
    vod->prev.time = BLI_time_now_seconds();
  }

  /* The first bridge version intentionally maps every pivot policy to Blender's current
   * navigation preference. The policy remains part of the API for a later Clarity-specific pivot. */
  UNUSED_VARS(params.orbit_around_selection, params.pivot_policy, params.explicit_pivot);

  return std::make_unique<BlenderNavigationSession>(vod, type, params.invert_direction);
}

}  // namespace blender::ed::view3d
