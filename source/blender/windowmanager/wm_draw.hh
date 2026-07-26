/* SPDX-FileCopyrightText: 2007 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup wm
 */

#pragma once

namespace blender {

struct ARegion;
struct GPUOffScreen;
namespace gpu {
class Texture;
}
struct GPUViewport;
struct ScrArea;
struct bContext;
struct wmWindow;

struct wmDrawBuffer {
  GPUOffScreen *offscreen;
  GPUViewport *viewport;
  bool stereo;
  int bound_view;
  int viewport_size[2];
  int diagnostic_reset_reason;
};

/* `wm_draw.cc` */

void wm_draw_update(bContext *C);
void wm_draw_region_clear(wmWindow *win, ARegion *region);
void wm_draw_region_cached_composite_tag(wmWindow *win);
void wm_draw_region_blend(ARegion *region, int view, bool blend);
void wm_draw_region_test(bContext *C, ScrArea *area, ARegion *region);

gpu::Texture *wm_draw_region_texture(ARegion *region, int view);

}  // namespace blender
