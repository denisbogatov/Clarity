/* SPDX-FileCopyrightText: 2024 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edinterface
 */

#include <algorithm>
#include <cfloat>
#include <memory>

#include "BKE_colortools.hh"
#include "BKE_context.hh"
#include "BKE_library.hh"

#include "BLI_bounds.hh"
#include "BLI_map.hh"
#include "BLI_math_base.h"
#include "BLI_math_vector_types.hh"
#include "BLI_rect.h"
#include "BLI_string_ref.hh"

#include "BLT_translation.hh"

#include "DNA_scene_types.h"

#include "ED_screen.hh"
#include "ED_undo.hh"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "WM_api.hh"

#include "UI_interface_layout.hh"
#include "interface_intern.hh"
#include "interface_templates_intern.hh"

namespace blender::ui {

using blender::Vector;

struct CurveRuntimeProperties {
  CurveMapPoint *last_pt = nullptr;
  float2 last_pos;
};

static bool curvemap_can_zoom_out(CurveMapping *cumap)
{
  return (cumap->flag & CUMA_DO_CLIP) == 0 ||
         (BLI_rctf_size_x(&cumap->curr) < BLI_rctf_size_x(&cumap->clipr));
}

static bool curvemap_can_zoom_in(CurveMapping *cumap)
{
  return (cumap->flag & CUMA_DO_CLIP) == 0 ||
         (BLI_rctf_size_x(&cumap->curr) > CURVE_ZOOM_MAX * BLI_rctf_size_x(&cumap->clipr));
}

static void curvemap_zoom(CurveMapping &cumap, const float scale)
{
  const Bounds<float2> curr_bounds(float2(cumap.curr.xmin, cumap.curr.ymin),
                                   float2(cumap.curr.xmax, cumap.curr.ymax));
  const float2 offset = curr_bounds.size() * 0.5f * (scale - 1.0f);
  const Bounds<float2> new_bounds(curr_bounds.min - offset, curr_bounds.max + offset);

  Bounds<float2> clamped_bounds = new_bounds;
  /* Clamp to clip bounds if enabled, snap if the difference is small. */
  if (cumap.flag & CUMA_DO_CLIP) {
    const Bounds<float2> clip_bounds(float2(cumap.clipr.xmin, cumap.clipr.ymin),
                                     float2(cumap.clipr.xmax, cumap.clipr.ymax));
    const float2 threshold = 0.01f * clip_bounds.size();
    if (clamped_bounds.min.x < clip_bounds.min.x + threshold.x) {
      clamped_bounds.min.x = clip_bounds.min.x;
    }
    if (clamped_bounds.min.y < clip_bounds.min.y + threshold.y) {
      clamped_bounds.min.y = clip_bounds.min.y;
    }
    if (clamped_bounds.max.x > clip_bounds.max.x - threshold.x) {
      clamped_bounds.max.x = clip_bounds.max.x;
    }
    if (clamped_bounds.max.y > clip_bounds.max.y - threshold.y) {
      clamped_bounds.max.y = clip_bounds.max.y;
    }
  }
  cumap.curr.xmin = clamped_bounds.min.x;
  cumap.curr.ymin = clamped_bounds.min.y;
  cumap.curr.xmax = clamped_bounds.max.x;
  cumap.curr.ymax = clamped_bounds.max.y;
}

static void curvemap_buttons_zoom_in(bContext *C, CurveMapping *cumap)
{
  if (!curvemap_can_zoom_in(cumap)) {
    return;
  }

  curvemap_zoom(*cumap, 0.7692f);

  ED_region_tag_redraw(CTX_wm_region(C));
}

static void curvemap_buttons_zoom_out(bContext *C, CurveMapping *cumap)
{
  if (!curvemap_can_zoom_out(cumap)) {
    return;
  }

  curvemap_zoom(*cumap, 1.3f);

  ED_region_tag_redraw(CTX_wm_region(C));
}

/* NOTE: this is a block-menu, needs 0 events, otherwise the menu closes */
static Block *curvemap_clipping_func(bContext *C, ARegion *region, void *cumap_v)
{
  CurveMapping *cumap = static_cast<CurveMapping *>(cumap_v);
  Button *bt;
  const float width = 8 * UI_UNIT_X;

  Block *block = block_begin(C, region, __func__, EmbossType::Emboss);
  block_flag_enable(block, BLOCK_KEEP_OPEN | BLOCK_MOVEMOUSE_QUIT);
  block_theme_style_set(block, BLOCK_THEME_STYLE_POPUP);

  bt = uiDefButBit(block,
                   ButtonType::Checkbox,
                   CUMA_DO_CLIP,
                   IFACE_("Clipping"),
                   0,
                   5 * UI_UNIT_Y,
                   width,
                   UI_UNIT_Y,
                   &cumap->flag,
                   0.0,
                   0.0,
                   "");
  button_func_set(bt, [cumap](bContext & /*C*/) { BKE_curvemapping_changed(cumap, false); });

  block_align_begin(block);
  bt = uiDefButV(block,
                 ButtonType::Num,
                 IFACE_("Min X:"),
                 0,
                 4 * UI_UNIT_Y,
                 width,
                 UI_UNIT_Y,
                 &cumap->clipr.xmin,
                 -100.0,
                 cumap->clipr.xmax,
                 "");
  button_number_step_size_set(bt, 10);
  button_number_precision_set(bt, 2);
  bt = uiDefButV(block,
                 ButtonType::Num,
                 IFACE_("Min Y:"),
                 0,
                 3 * UI_UNIT_Y,
                 width,
                 UI_UNIT_Y,
                 &cumap->clipr.ymin,
                 -100.0,
                 cumap->clipr.ymax,
                 "");
  button_number_step_size_set(bt, 10);
  button_number_precision_set(bt, 2);
  bt = uiDefButV(block,
                 ButtonType::Num,
                 IFACE_("Max X:"),
                 0,
                 2 * UI_UNIT_Y,
                 width,
                 UI_UNIT_Y,
                 &cumap->clipr.xmax,
                 cumap->clipr.xmin,
                 100.0,
                 "");
  button_number_step_size_set(bt, 10);
  button_number_precision_set(bt, 2);
  bt = uiDefButV(block,
                 ButtonType::Num,
                 IFACE_("Max Y:"),
                 0,
                 UI_UNIT_Y,
                 width,
                 UI_UNIT_Y,
                 &cumap->clipr.ymax,
                 cumap->clipr.ymin,
                 100.0,
                 "");
  button_number_step_size_set(bt, 10);
  button_number_precision_set(bt, 2);

  block_bounds_set_normal(block, 0.3f * U.widget_unit);
  block_direction_set(block, UI_DIR_DOWN);

  return block;
}

static Block *curvemap_tools_func(
    bContext *C, ARegion *region, RNAUpdateCb &cb, bool show_extend, CurveMapSlopeType reset_mode)
{
  PointerRNA cumap_ptr = RNA_property_pointer_get(&cb.ptr, cb.prop);
  CurveMapping *cumap = static_cast<CurveMapping *>(cumap_ptr.data);

  short yco = 0;
  const short menuwidth = 10 * UI_UNIT_X;

  Block *block = block_begin(C, region, __func__, EmbossType::Emboss);

  {
    Button *but = uiDefIconTextBut(block,
                                   ButtonType::ButMenu,
                                   ICON_BLANK1,
                                   IFACE_("Reset View"),
                                   0,
                                   yco -= UI_UNIT_Y,
                                   menuwidth,
                                   UI_UNIT_Y,
                                   nullptr,
                                   "");
    button_func_set(but, [cumap](bContext &C) {
      BKE_curvemapping_reset_view(cumap);
      ED_region_tag_redraw(CTX_wm_region(&C));
    });
  }

  if (show_extend && !(cumap->flag & CUMA_USE_WRAPPING)) {
    {
      Button *but = uiDefIconTextBut(block,
                                     ButtonType::ButMenu,
                                     ICON_BLANK1,
                                     IFACE_("Extend Horizontal"),
                                     0,
                                     yco -= UI_UNIT_Y,
                                     menuwidth,
                                     UI_UNIT_Y,
                                     nullptr,
                                     "");
      button_func_set(but, [cumap, cb](bContext &C) {
        cumap->flag &= ~CUMA_EXTEND_EXTRAPOLATE;
        BKE_curvemapping_changed(cumap, false);
        rna_update_cb(C, cb);
        ED_undo_push(&C, "CurveMap tools");
        ED_region_tag_redraw(CTX_wm_region(&C));
      });
    }
    {
      Button *but = uiDefIconTextBut(block,
                                     ButtonType::ButMenu,
                                     ICON_BLANK1,
                                     IFACE_("Extend Extrapolated"),
                                     0,
                                     yco -= UI_UNIT_Y,
                                     menuwidth,
                                     UI_UNIT_Y,
                                     nullptr,
                                     "");
      button_func_set(but, [cumap, cb](bContext &C) {
        cumap->flag |= CUMA_EXTEND_EXTRAPOLATE;
        BKE_curvemapping_changed(cumap, false);
        rna_update_cb(C, cb);
        ED_undo_push(&C, "CurveMap tools");
        ED_region_tag_redraw(CTX_wm_region(&C));
      });
    }
  }

  {
    Button *but = uiDefIconTextBut(block,
                                   ButtonType::ButMenu,
                                   ICON_BLANK1,
                                   IFACE_("Reset Curve"),
                                   0,
                                   yco -= UI_UNIT_Y,
                                   menuwidth,
                                   UI_UNIT_Y,
                                   nullptr,
                                   "");
    button_func_set(but, [cumap, cb, reset_mode](bContext &C) {
      CurveMap *cuma = cumap->cm + cumap->cur;
      BKE_curvemap_reset(cuma, &cumap->clipr, cumap->preset, reset_mode);
      BKE_curvemapping_changed(cumap, false);
      rna_update_cb(C, cb);
      ED_undo_push(&C, "CurveMap tools");
      ED_region_tag_redraw(CTX_wm_region(&C));
    });
  }

  block_direction_set(block, UI_DIR_DOWN);
  block_bounds_set_text(block, 3.0f * UI_UNIT_X);

  return block;
}

static Block *curvemap_tools_posslope_func(bContext *C, ARegion *region, void *cb_v)
{
  return curvemap_tools_func(
      C, region, *static_cast<RNAUpdateCb *>(cb_v), true, CurveMapSlopeType::Positive);
}

static Block *curvemap_tools_negslope_func(bContext *C, ARegion *region, void *cb_v)
{
  return curvemap_tools_func(
      C, region, *static_cast<RNAUpdateCb *>(cb_v), true, CurveMapSlopeType::Negative);
}

static Block *curvemap_brush_tools_func(bContext *C, ARegion *region, void *cb_v)
{
  return curvemap_tools_func(
      C, region, *static_cast<RNAUpdateCb *>(cb_v), false, CurveMapSlopeType::Positive);
}

static Block *curvemap_brush_tools_negslope_func(bContext *C, ARegion *region, void *cb_v)
{
  return curvemap_tools_func(
      C, region, *static_cast<RNAUpdateCb *>(cb_v), false, CurveMapSlopeType::Negative);
}

static void curvemap_buttons_redraw(bContext &C)
{
  ED_region_tag_redraw(CTX_wm_region(&C));
}

static void add_preset_button(Block *block,
                              const float dx,
                              const int icon,
                              std::optional<StringRef> tip,
                              CurveMapping *cumap,
                              const bool neg_slope,
                              const eCurveMappingPreset preset,
                              const RNAUpdateCb &cb)
{
  Button *bt = uiDefIconBut(
      block, ButtonType::Row, icon, 0, 0, dx, dx, &cumap->cur, 0.0, 3.0, tip);
  button_func_set(bt, [&, cumap, neg_slope, preset, cb](bContext &C) {
    const CurveMapSlopeType slope = neg_slope ? CurveMapSlopeType::Negative :
                                                CurveMapSlopeType::Positive;
    cumap->flag &= ~CUMA_EXTEND_EXTRAPOLATE;
    cumap->preset = preset;
    BKE_curvemap_reset(cumap->cm, &cumap->clipr, cumap->preset, slope);
    BKE_curvemapping_changed(cumap, false);
    rna_update_cb(C, cb);
  });
}

/**
 * \note Still unsure how this call evolves.
 *
 * \param labeltype: Used for defining which curve-channels to show.
 */
static void curvemap_buttons_layout(Layout *layout,
                                    PointerRNA *ptr,
                                    char labeltype,
                                    bool levels,
                                    bool brush,
                                    bool neg_slope,
                                    bool tone,
                                    bool presets,
                                    const RNAUpdateCb &cb)
{
  CurveMapping *cumap = static_cast<CurveMapping *>(ptr->data);
  CurveMap *cm = &cumap->cm[cumap->cur];
  Button *bt;
  const float dx = UI_UNIT_X;
  eButGradientType bg = GRAD_NONE;

  Block *block = layout->block();

  block_emboss_set(block, EmbossType::Emboss);

  if (tone) {
    Layout &split = layout->split(0.0f, false);
    split.row(false).prop(ptr, "tone", ITEM_R_EXPAND, std::nullopt, ICON_NONE);
  }

  /* curve chooser */
  Layout *row = &layout->row(false);

  if (labeltype == 'v') {
    /* vector */
    Layout &sub = row->row(true);
    sub.alignment_set(LayoutAlign::Left);

    if (cumap->cm[0].curve) {
      bt = uiDefButV(block, ButtonType::Row, "X", 0, 0, dx, dx, &cumap->cur, 0.0, 0.0, "");
      button_func_set(bt, curvemap_buttons_redraw);
    }
    if (cumap->cm[1].curve) {
      bt = uiDefButV(block, ButtonType::Row, "Y", 0, 0, dx, dx, &cumap->cur, 0.0, 1.0, "");
      button_func_set(bt, curvemap_buttons_redraw);
    }
    if (cumap->cm[2].curve) {
      bt = uiDefButV(block, ButtonType::Row, "Z", 0, 0, dx, dx, &cumap->cur, 0.0, 2.0, "");
      button_func_set(bt, curvemap_buttons_redraw);
    }
  }
  else if (labeltype == 'c' && cumap->tone != CURVE_TONE_FILMLIKE) {
    /* color */
    Layout &sub = row->row(true);
    sub.alignment_set(LayoutAlign::Left);

    if (cumap->cm[3].curve) {
      bt = uiDefButV(block,
                     ButtonType::Row,
                     CTX_IFACE_(BLT_I18NCONTEXT_COLOR, "C"),
                     0,
                     0,
                     dx,
                     dx,
                     &cumap->cur,
                     0.0,
                     3.0,
                     TIP_("Combined channels"));
      button_func_set(bt, curvemap_buttons_redraw);
    }
    if (cumap->cm[0].curve) {
      bt = uiDefButV(block,
                     ButtonType::Row,
                     CTX_IFACE_(BLT_I18NCONTEXT_COLOR, "R"),
                     0,
                     0,
                     dx,
                     dx,
                     &cumap->cur,
                     0.0,
                     0.0,
                     TIP_("Red channel"));
      button_func_set(bt, curvemap_buttons_redraw);
    }
    if (cumap->cm[1].curve) {
      bt = uiDefButV(block,
                     ButtonType::Row,
                     CTX_IFACE_(BLT_I18NCONTEXT_COLOR, "G"),
                     0,
                     0,
                     dx,
                     dx,
                     &cumap->cur,
                     0.0,
                     1.0,
                     TIP_("Green channel"));
      button_func_set(bt, curvemap_buttons_redraw);
    }
    if (cumap->cm[2].curve) {
      bt = uiDefButV(block,
                     ButtonType::Row,
                     CTX_IFACE_(BLT_I18NCONTEXT_COLOR, "B"),
                     0,
                     0,
                     dx,
                     dx,
                     &cumap->cur,
                     0.0,
                     2.0,
                     TIP_("Blue channel"));
      button_func_set(bt, curvemap_buttons_redraw);
    }
  }
  else if (labeltype == 'h') {
    /* HSV */
    Layout &sub = row->row(true);
    sub.alignment_set(LayoutAlign::Left);

    if (cumap->cm[0].curve) {
      bt = uiDefButV(block,
                     ButtonType::Row,
                     IFACE_("H"),
                     0,
                     0,
                     dx,
                     dx,
                     &cumap->cur,
                     0.0,
                     0.0,
                     TIP_("Hue level"));
      button_func_set(bt, curvemap_buttons_redraw);
    }
    if (cumap->cm[1].curve) {
      bt = uiDefButV(block,
                     ButtonType::Row,
                     IFACE_("S"),
                     0,
                     0,
                     dx,
                     dx,
                     &cumap->cur,
                     0.0,
                     1.0,
                     TIP_("Saturation level"));
      button_func_set(bt, curvemap_buttons_redraw);
    }
    if (cumap->cm[2].curve) {
      bt = uiDefButV(block,
                     ButtonType::Row,
                     IFACE_("V"),
                     0,
                     0,
                     dx,
                     dx,
                     &cumap->cur,
                     0.0,
                     2.0,
                     TIP_("Value level"));
      button_func_set(bt, curvemap_buttons_redraw);
    }
  }
  else {
    row->alignment_set(LayoutAlign::Right);
  }

  if (labeltype == 'h') {
    bg = GRAD_H;
  }

  /* operation buttons */
  /* (Right aligned) */
  Layout &sub = row->row(true);
  sub.alignment_set(LayoutAlign::Right);

  if (!(cumap->flag & CUMA_USE_WRAPPING)) {
    /* Zoom in */
    bt = uiDefIconBut(
        block, ButtonType::But, ICON_ZOOM_IN, 0, 0, dx, dx, nullptr, 0.0, 0.0, TIP_("Zoom in"));
    button_func_set(bt, [cumap](bContext &C) { curvemap_buttons_zoom_in(&C, cumap); });
    if (!curvemap_can_zoom_in(cumap)) {
      button_disable(bt, "");
    }

    /* Zoom out */
    bt = uiDefIconBut(
        block, ButtonType::But, ICON_ZOOM_OUT, 0, 0, dx, dx, nullptr, 0.0, 0.0, TIP_("Zoom out"));
    button_func_set(bt, [cumap](bContext &C) { curvemap_buttons_zoom_out(&C, cumap); });
    if (!curvemap_can_zoom_out(cumap)) {
      button_disable(bt, "");
    }

    /* Clipping button. */
    const int icon = (cumap->flag & CUMA_DO_CLIP) ? ICON_CLIPUV_HLT : ICON_CLIPUV_DEHLT;
    bt = uiDefIconBlockBut(
        block, curvemap_clipping_func, cumap, icon, 0, 0, dx, dx, TIP_("Clipping options"));
    bt->drawflag &= ~BUT_ICON_LEFT;
    button_func_set(bt, [cb](bContext &C) { rna_update_cb(C, cb); });
  }

  RNAUpdateCb *tools_cb = MEM_new<RNAUpdateCb>(__func__, cb);
  if (brush && neg_slope) {
    bt = uiDefIconBlockBut(block,
                           curvemap_brush_tools_negslope_func,
                           tools_cb,
                           ICON_NONE,
                           0,
                           0,
                           dx,
                           dx,
                           TIP_("Tools"));
  }
  else if (brush) {
    bt = uiDefIconBlockBut(
        block, curvemap_brush_tools_func, tools_cb, ICON_NONE, 0, 0, dx, dx, TIP_("Tools"));
  }
  else if (neg_slope) {
    bt = uiDefIconBlockBut(
        block, curvemap_tools_negslope_func, tools_cb, ICON_NONE, 0, 0, dx, dx, TIP_("Tools"));
  }
  else {
    bt = uiDefIconBlockBut(
        block, curvemap_tools_posslope_func, tools_cb, ICON_NONE, 0, 0, dx, dx, TIP_("Tools"));
  }
  /* Pass ownership of `tools_cb` to the button. */
  button_funcN_set(
      bt,
      [](bContext *, void *, void *) {},
      tools_cb,
      nullptr,
      but_func_argN_free<RNAUpdateCb>,
      but_func_argN_copy<RNAUpdateCb>);

  block_funcN_set(block,
                  rna_update_cb,
                  MEM_new<RNAUpdateCb>(__func__, cb),
                  nullptr,
                  but_func_argN_free<RNAUpdateCb>,
                  but_func_argN_copy<RNAUpdateCb>);

  /* Curve itself. */
  const int size = max_ii(layout->width(), UI_UNIT_X);
  row = &layout->row(false);
  ButtonCurveMapping *curve_but = static_cast<ButtonCurveMapping *>(
      uiDefBut(block,
               ButtonType::Curve,
               IFACE_("Edit Curve Map"),
               0,
               0,
               size,
               8.0f * UI_UNIT_X,
               cumap,
               0.0f,
               1.0f,
               ""));
  curve_but->gradient_type = bg;
  if (!layout->active()) {
    button_flag_enable(curve_but, BUT_INACTIVE);
  }

  /* Sliders for selected curve point. */
  Vector<CurveMapPoint *> selected_points;
  bool point_last_or_first = false;
  for (int i = 0; i < cm->totpoint; i++) {
    const bool selected = cm->curve[i].flag & CUMA_SELECT;
    if (selected) {
      selected_points.append(&cm->curve[i]);
    }
    if (ELEM(i, 0, cm->totpoint - 1) && selected) {
      point_last_or_first = true;
    }
  }

  if (!selected_points.is_empty()) {
    CurveMap *active_cm = cumap->cm + cumap->cur;

    rctf bounds;
    if (cumap->flag & CUMA_DO_CLIP) {
      bounds = cumap->clipr;
    }
    else {
      bounds.xmin = bounds.ymin = -1000.0;
      bounds.xmax = bounds.ymax = 1000.0;
    }

    block_emboss_set(block, EmbossType::Emboss);

    layout->row(true);

    /* Curve handle buttons. */
    bt = uiDefIconBut(block,
                      ButtonType::But,
                      ICON_HANDLE_AUTO,
                      0,
                      UI_UNIT_Y,
                      UI_UNIT_X,
                      UI_UNIT_Y,
                      nullptr,
                      0.0,
                      0.0,
                      TIP_("Auto handle"));
    button_func_set(bt, [cumap, cb](bContext &C) {
      CurveMap *cuma = cumap->cm + cumap->cur;
      BKE_curvemap_handle_set(cuma, HD_AUTO);
      BKE_curvemapping_changed(cumap, false);
      rna_update_cb(C, cb);
    });

    for (const CurveMapPoint *cmp : selected_points) {
      const bool auto_anim_vec = ((cmp->flag & CUMA_HANDLE_AUTO_ANIM) == false) &&
                                 ((cmp->flag & CUMA_HANDLE_VECTOR) == false);
      if (auto_anim_vec) {
        bt->flag |= UI_SELECT_DRAW;
      }
    }

    bt = uiDefIconBut(block,
                      ButtonType::But,
                      ICON_HANDLE_VECTOR,
                      0,
                      UI_UNIT_Y,
                      UI_UNIT_X,
                      UI_UNIT_Y,
                      nullptr,
                      0.0,
                      0.0,
                      TIP_("Vector handle"));
    button_func_set(bt, [cumap, cb](bContext &C) {
      CurveMap *cuma = cumap->cm + cumap->cur;
      BKE_curvemap_handle_set(cuma, HD_VECT);
      BKE_curvemapping_changed(cumap, false);
      rna_update_cb(C, cb);
    });

    for (const CurveMapPoint *cmp : selected_points) {
      const bool vec = (cmp->flag & CUMA_HANDLE_VECTOR);
      if (vec) {
        bt->flag |= UI_SELECT_DRAW;
      }
    }

    bt = uiDefIconBut(block,
                      ButtonType::But,
                      ICON_HANDLE_AUTOCLAMPED,
                      0,
                      UI_UNIT_Y,
                      UI_UNIT_X,
                      UI_UNIT_Y,
                      nullptr,
                      0.0,
                      0.0,
                      TIP_("Auto clamped"));
    button_func_set(bt, [cumap, cb](bContext &C) {
      CurveMap *cuma = cumap->cm + cumap->cur;
      BKE_curvemap_handle_set(cuma, HD_AUTO_ANIM);
      BKE_curvemapping_changed(cumap, false);
      rna_update_cb(C, cb);
    });

    for (const CurveMapPoint *cmp : selected_points) {
      const bool auto_anim = (cmp->flag & CUMA_HANDLE_AUTO_ANIM);
      if (auto_anim) {
        bt->flag |= UI_SELECT_DRAW;
      }
    }

    /* Curve handle position */
    auto curve_runtime = std::make_shared<CurveRuntimeProperties>();
    curve_runtime->last_pt = BKE_curvemap_active_get(active_cm);
    curve_runtime->last_pos.x = curve_runtime->last_pt->x;
    curve_runtime->last_pos.y = curve_runtime->last_pt->y;

    /* While the slider controls the active element, all selected points move together.
     * Contract the slider range so the outermost selected points stay within the clip region. */
    rctf slider_bounds = bounds;
    if (selected_points.size() > 1) {
      rctf selection_bounds;
      BLI_rctf_init_minmax(&selection_bounds);

      /* The slider only shows the active point's position, but moves all selected points by the
       * same delta. Clamp the range so points at the edges of the selection can't be moved outside
       * the clip region. */
      for (const CurveMapPoint *cmp : selected_points) {
        const float loc[2] = {cmp->x, cmp->y};
        BLI_rctf_do_minmax_v(&selection_bounds, loc);
      }

      slider_bounds.xmin += curve_runtime->last_pt->x - selection_bounds.xmin;
      slider_bounds.xmax += curve_runtime->last_pt->x - selection_bounds.xmax;
      slider_bounds.ymin += curve_runtime->last_pt->y - selection_bounds.ymin;
      slider_bounds.ymax += curve_runtime->last_pt->y - selection_bounds.ymax;
    }

    const char *const axis_labels[2] = {"X:", "Y:"};
    float *const axis_ptrs[2] = {&curve_runtime->last_pt->x, &curve_runtime->last_pt->y};
    const float axis_min[2] = {slider_bounds.xmin, slider_bounds.ymin};
    const float axis_max[2] = {slider_bounds.xmax, slider_bounds.ymax};
    for (int axis = 0; axis < 2; axis++) {
      bt = uiDefButV(block,
                     ButtonType::Num,
                     axis_labels[axis],
                     0,
                     (2 - axis) * UI_UNIT_Y,
                     UI_UNIT_X * 10,
                     UI_UNIT_Y,
                     axis_ptrs[axis],
                     axis_min[axis],
                     axis_max[axis],
                     "");
      button_number_step_size_set(bt, 1);
      button_number_precision_set(bt, 5);
      if (selected_points.size() == 1) {
        /* Simplified logic */
        button_func_set(bt, [cumap, cb](bContext &C) {
          BKE_curvemapping_changed(cumap, true);
          rna_update_cb(C, cb);
        });
      }
      else {
        button_func_set(bt, [cumap, cb, curve_runtime, axis](bContext &C) {
          CurveMap *cuma = cumap->cm + cumap->cur;
          float *last_pt_co = &curve_runtime->last_pt->x;
          const float delta = last_pt_co[axis] - curve_runtime->last_pos[axis];
          /* Logically `-= delta`, better restore the original value. */
          last_pt_co[axis] = curve_runtime->last_pos[axis];
          float2 offset(0.0f);
          offset[axis] = delta;
          BKE_curvemap_translate_selection(cuma, offset);
          BKE_curvemapping_changed(cumap, true);
          rna_update_cb(C, cb);

          /* Update the active point if the pointer changed. */
          curve_runtime->last_pt = BKE_curvemap_active_get(cuma);
          last_pt_co = &curve_runtime->last_pt->x;
          curve_runtime->last_pos[axis] = last_pt_co[axis];
        });
      }
    }

    /* Curve handle delete point */
    bt = uiDefIconBut(
        block, ButtonType::But, ICON_X, 0, 0, dx, dx, nullptr, 0.0, 0.0, TIP_("Delete points"));
    button_func_set(bt, [cumap, cb](bContext &C) {
      BKE_curvemap_remove(cumap->cm + cumap->cur, SELECT);
      BKE_curvemapping_changed(cumap, false);
      rna_update_cb(C, cb);
    });
    if (point_last_or_first) {
      button_flag_enable(bt, BUT_DISABLED);
    }
  }

  /* black/white levels */
  if (levels) {
    Layout &split = layout->split(0.0f, false);
    split.column(false).prop(ptr, "black_level", ITEM_R_EXPAND, std::nullopt, ICON_NONE);
    split.column(false).prop(ptr, "white_level", ITEM_R_EXPAND, std::nullopt, ICON_NONE);

    layout->row(false);
    bt = uiDefBut(block,
                  ButtonType::But,
                  IFACE_("Reset"),
                  0,
                  0,
                  UI_UNIT_X * 10,
                  UI_UNIT_Y,
                  nullptr,
                  0.0f,
                  0.0f,
                  TIP_("Reset curves and black/white point"));
    button_func_set(bt, [cumap, cb](bContext &C) {
      cumap->preset = CURVE_PRESET_LINE;
      for (int a = 0; a < CM_TOT; a++) {
        BKE_curvemap_reset(
            cumap->cm + a, &cumap->clipr, cumap->preset, CurveMapSlopeType::Positive);
      }

      cumap->black[0] = cumap->black[1] = cumap->black[2] = 0.0f;
      cumap->white[0] = cumap->white[1] = cumap->white[2] = 1.0f;
      BKE_curvemapping_set_black_white(cumap, nullptr, nullptr);

      BKE_curvemapping_changed(cumap, false);
      rna_update_cb(C, cb);
    });
  }

  if (presets) {
    row = &layout->row(true);
    sub.alignment_set(LayoutAlign::Left);
    add_preset_button(block,
                      dx,
                      ICON_SMOOTHCURVE,
                      TIP_("Smooth preset"),
                      cumap,
                      neg_slope,
                      CURVE_PRESET_SMOOTH,
                      cb);
    add_preset_button(block,
                      dx,
                      ICON_SPHERECURVE,
                      TIP_("Round preset"),
                      cumap,
                      neg_slope,
                      CURVE_PRESET_ROUND,
                      cb);
    add_preset_button(
        block, dx, ICON_ROOTCURVE, TIP_("Root preset"), cumap, neg_slope, CURVE_PRESET_ROOT, cb);
    add_preset_button(block,
                      dx,
                      ICON_SHARPCURVE,
                      TIP_("Sharp preset"),
                      cumap,
                      neg_slope,
                      CURVE_PRESET_SHARP,
                      cb);
    add_preset_button(
        block, dx, ICON_LINCURVE, TIP_("Linear preset"), cumap, neg_slope, CURVE_PRESET_LINE, cb);
    add_preset_button(
        block, dx, ICON_NOCURVE, TIP_("Constant preset"), cumap, neg_slope, CURVE_PRESET_MAX, cb);
  }

  block_funcN_set(block, nullptr, nullptr, nullptr);
}

void template_curve_mapping(Layout *layout,
                            PointerRNA *ptr,
                            const StringRefNull propname,
                            int type,
                            bool levels,
                            bool brush,
                            bool neg_slope,
                            bool tone,
                            bool presets)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, propname.c_str());
  Block *block = layout->block();

  if (!prop) {
    RNA_warning(
        "curve property not found: %s.%s", RNA_struct_identifier(ptr->type), propname.c_str());
    return;
  }

  if (RNA_property_type(prop) != PROP_POINTER) {
    RNA_warning(
        "curve is not a pointer: %s.%s", RNA_struct_identifier(ptr->type), propname.c_str());
    return;
  }

  PointerRNA cptr = RNA_property_pointer_get(ptr, prop);
  if (!cptr.data || !RNA_struct_is_a(cptr.type, RNA_CurveMapping)) {
    return;
  }

  ID *id = cptr.owner_id;
  block_lock_set(block, (id && !ID_IS_EDITABLE(id)), ERROR_LIBDATA_MESSAGE);

  curvemap_buttons_layout(
      layout, &cptr, type, levels, brush, neg_slope, tone, presets, RNAUpdateCb{*ptr, prop});

  block_lock_clear(block);
}

namespace {

struct SoftSelectionDisplayPoint {
  SoftSelectionCurvePoint point;
  int source_index;
};

/* Must exceed CurveMapping's 1% duplicate-removal threshold on mouse release. */
constexpr float soft_selection_duplicate_display_epsilon = 0.012f;
constexpr float soft_selection_duplicate_restore_epsilon = 0.02f;

static std::shared_ptr<CurveMapping> soft_selection_mapping_create(
    const SoftSelectionSettings &settings)
{
  std::shared_ptr<CurveMapping> mapping(
      BKE_curvemapping_add(1, 0.0f, 0.0f, 1.0f, 1.0f), BKE_curvemapping_free);
  mapping->flag |= CUMA_DO_CLIP;
  mapping->flag &= ~CUMA_EXTEND_EXTRAPOLATE;

  Vector<SoftSelectionDisplayPoint> points;
  const int source_count = std::clamp(
      settings.curve_point_count, 0, int(SOFT_SELECTION_CURVE_POINT_MAX));
  points.reserve(std::max(source_count, 2));
  for (int index = 0; index < source_count; index++) {
    points.append({settings.curve_points[index], index});
  }
  std::stable_sort(points.begin(),
                   points.end(),
                   [](const SoftSelectionDisplayPoint &a, const SoftSelectionDisplayPoint &b) {
                     return a.point.position < b.point.position;
                   });

  if (points.is_empty()) {
    SoftSelectionCurvePoint first;
    first.position = 0.0f;
    first.value = 1.0f;
    SoftSelectionCurvePoint last;
    last.position = 1.0f;
    last.value = 0.0f;
    points.append({first, -1});
    points.append({last, -1});
  }
  else if (points.size() == 1) {
    SoftSelectionCurvePoint proxy = points.first().point;
    proxy.position = (proxy.position < 0.5f) ? 1.0f : 0.0f;
    points.append({proxy, -1});
    std::stable_sort(points.begin(),
                     points.end(),
                     [](const SoftSelectionDisplayPoint &a, const SoftSelectionDisplayPoint &b) {
                       return a.point.position < b.point.position;
                     });
  }

  /* CurveMapping requires a strictly increasing X domain for stable endpoint handles. Maya ramps
   * intentionally allow duplicate positions (Linear and Stairs use them), so separate duplicates
   * by a small editor-only offset. The exact persistent positions are restored below. */
  for (int group_start = 0; group_start < points.size();) {
    int group_end = group_start + 1;
    while (group_end < points.size() &&
           points[group_end].point.position == points[group_start].point.position)
    {
      group_end++;
    }
    const int group_size = group_end - group_start;
    if (group_size > 1) {
      const float span = soft_selection_duplicate_display_epsilon * float(group_size - 1);
      const float first_position = std::clamp(
          points[group_start].point.position - span * 0.5f, 0.0f, 1.0f - span);
      for (int index = group_start; index < group_end; index++) {
        points[index].point.position = first_position +
                                       soft_selection_duplicate_display_epsilon *
                                           float(index - group_start);
      }
    }
    group_start = group_end;
  }

  BKE_curvemapping_free_data_single(mapping.get(), 0);
  CurveMap &curve = mapping->cm[0];
  curve.totpoint = short(points.size());
  curve.curve = MEM_new_array<CurveMapPoint>(points.size(), "soft selection curve editor");
  curve.default_handle_type = CUMA_HANDLE_AUTO_ANIM;

  for (const int index : points.index_range()) {
    const SoftSelectionDisplayPoint &source = points[index];
    CurveMapPoint &target = curve.curve[index];
    target.x = std::clamp(source.point.position, 0.0f, 1.0f);
    target.y = std::clamp(source.point.value, 0.0f, 1.0f);
    if (ELEM(source.point.interpolation, SOFT_SELECT_INTERP_NONE, SOFT_SELECT_INTERP_LINEAR)) {
      target.flag |= CUMA_HANDLE_VECTOR;
    }
    else if (source.point.interpolation == SOFT_SELECT_INTERP_SMOOTH) {
      target.flag |= CUMA_HANDLE_AUTO_ANIM;
    }
    if (source.source_index == settings.active_curve_point) {
      target.flag |= CUMA_SELECT | CUMA_ACTIVE;
    }
  }

  BKE_curvemapping_changed(mapping.get(), false);
  BKE_curvemapping_init(mapping.get());
  return mapping;
}

static void soft_selection_mapping_store(const CurveMapping &mapping,
                                         SoftSelectionSettings &settings)
{
  const CurveMap &curve = mapping.cm[0];
  const int old_count = std::clamp(
      settings.curve_point_count, 0, int(SOFT_SELECTION_CURVE_POINT_MAX));
  const int new_count = std::clamp(
      int(curve.totpoint), 1, int(SOFT_SELECTION_CURVE_POINT_MAX));
  SoftSelectionCurvePoint old_points[SOFT_SELECTION_CURVE_POINT_MAX];
  bool matched[SOFT_SELECTION_CURVE_POINT_MAX] = {};
  for (int index = 0; index < old_count; index++) {
    old_points[index] = settings.curve_points[index];
  }

  int active_index = 0;
  for (int index = 0; index < new_count; index++) {
    const CurveMapPoint &source = curve.curve[index];
    int nearest = -1;
    float nearest_distance = FLT_MAX;
    for (int candidate = 0; candidate < old_count; candidate++) {
      if (matched[candidate]) {
        continue;
      }
      const float dx = source.x - old_points[candidate].position;
      const float dy = source.y - old_points[candidate].value;
      const float distance = dx * dx + dy * dy;
      if (distance < nearest_distance) {
        nearest = candidate;
        nearest_distance = distance;
      }
    }

    SoftSelectionCurvePoint &target = settings.curve_points[index];
    const float editor_position = std::clamp(source.x, 0.0f, 1.0f);
    target.position = (nearest >= 0 &&
                       fabsf(editor_position - old_points[nearest].position) <=
                           soft_selection_duplicate_restore_epsilon) ?
                          old_points[nearest].position :
                          editor_position;
    target.value = std::clamp(source.y, 0.0f, 1.0f);
    target.interpolation = (nearest >= 0) ? old_points[nearest].interpolation :
                                           SOFT_SELECT_INTERP_SMOOTH;
    if (nearest >= 0) {
      matched[nearest] = true;
    }
    if (source.flag & CUMA_ACTIVE) {
      active_index = index;
    }
  }

  settings.curve_point_count = new_count;
  settings.active_curve_point = std::min(active_index, new_count - 1);
}

struct SoftSelectionCurveEditorState {
  std::shared_ptr<CurveMapping> mapping;
  int curve_point_count = 0;
  int active_curve_point = 0;
  SoftSelectionCurvePoint curve_points[SOFT_SELECTION_CURVE_POINT_MAX];

  void snapshot(const SoftSelectionSettings &settings)
  {
    curve_point_count = std::clamp(
        settings.curve_point_count, 0, int(SOFT_SELECTION_CURVE_POINT_MAX));
    active_curve_point = settings.active_curve_point;
    for (int index = 0; index < curve_point_count; index++) {
      curve_points[index] = settings.curve_points[index];
    }
  }

  bool matches(const SoftSelectionSettings &settings) const
  {
    const int count = std::clamp(
        settings.curve_point_count, 0, int(SOFT_SELECTION_CURVE_POINT_MAX));
    if (curve_point_count != count || active_curve_point != settings.active_curve_point) {
      return false;
    }
    for (int index = 0; index < count; index++) {
      const SoftSelectionCurvePoint &a = curve_points[index];
      const SoftSelectionCurvePoint &b = settings.curve_points[index];
      if (a.position != b.position || a.value != b.value ||
          a.interpolation != b.interpolation)
      {
        return false;
      }
    }
    return true;
  }
};

static std::shared_ptr<SoftSelectionCurveEditorState> soft_selection_editor_state_ensure(
    SoftSelectionSettings &settings)
{
  /* UI blocks are rebuilt while a button is being dragged. A weak cache lets the replacement
   * block reuse the same temporary CurveMapping without turning editor-only data into DNA. */
  static Map<SoftSelectionSettings *, std::weak_ptr<SoftSelectionCurveEditorState>> cache;
  cache.remove_if([](const auto item) { return item.value.expired(); });

  std::shared_ptr<SoftSelectionCurveEditorState> state;
  if (std::weak_ptr<SoftSelectionCurveEditorState> *cached = cache.lookup_ptr(&settings)) {
    state = cached->lock();
  }
  if (!state) {
    state = std::make_shared<SoftSelectionCurveEditorState>();
    cache.add_overwrite(&settings, state);
  }
  if (!state->mapping || !state->matches(settings)) {
    state->mapping = soft_selection_mapping_create(settings);
    state->snapshot(settings);
  }
  return state;
}

}  // namespace

void template_soft_selection_curve(Layout *layout, PointerRNA *ptr)
{
  if (!ptr || !ptr->data || !RNA_struct_is_a(ptr->type, RNA_SoftSelectionSettings)) {
    RNA_warning("expected SoftSelectionSettings");
    return;
  }

  SoftSelectionSettings *settings = ptr->data_as<SoftSelectionSettings>();
  std::shared_ptr<SoftSelectionCurveEditorState> state = soft_selection_editor_state_ensure(
      *settings);
  std::shared_ptr<CurveMapping> mapping = state->mapping;

  Block *block = layout->block();
  const int width = max_ii(layout->width(), UI_UNIT_X);
  ButtonCurveMapping *curve_button = static_cast<ButtonCurveMapping *>(
      uiDefBut(block,
               ButtonType::Curve,
               IFACE_("Edit Soft Selection Falloff"),
               0,
               0,
               width,
               6.0f * UI_UNIT_X,
               mapping.get(),
               0.0f,
               1.0f,
               TIP_("Drag points to edit the Maya soft-selection falloff; click the curve to add "
                    "a point")));
  curve_button->gradient_type = GRAD_NONE;
  curve_button->rnapoin = *ptr;
  button_func_set(curve_button, [state, mapping, settings](bContext &C) {
    soft_selection_mapping_store(*mapping, *settings);
    if (mapping->cm[0].totpoint > SOFT_SELECTION_CURVE_POINT_MAX) {
      /* The native curve widget can add more points than Maya's fixed 32-entry ramp. Rebuild the
       * editor proxy from the clamped persistent data on the next block redraw. */
      state->mapping = soft_selection_mapping_create(*settings);
    }
    state->snapshot(*settings);
    WM_event_add_notifier(&C, NC_SCENE | ND_TOOLSETTINGS, nullptr);
    ED_region_tag_redraw(CTX_wm_region(&C));
  });
  if (!layout->active()) {
    button_flag_enable(curve_button, BUT_INACTIVE);
  }
}

}  // namespace blender::ui
