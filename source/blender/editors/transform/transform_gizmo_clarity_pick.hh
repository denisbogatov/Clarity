/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 *
 * The rule that decides which manipulator handle the cursor means.
 *
 * Blender picks a gizmo by drawing every handle into a selection buffer inside a small rectangle
 * around the cursor and keeping whichever fragment is nearest the camera. That answers "what is in
 * front" - a fair question for objects in a scene, and the wrong one for a manipulator, whose
 * handles all sit at the same point and cross each other constantly. The cursor sitting exactly on
 * one ring while another ring passes a few pixels nearer the camera is not an ambiguity to a
 * person; it is to the depth buffer.
 *
 * Maya asks the question a hand asks: which handle is the cursor closest to, and when two are
 * equally close, which kind of handle is the one being aimed at. That is this rule. The distances
 * come from #ClarityPickCandidate, measured in pixels against the geometry that is actually drawn,
 * and nothing here depends on a view matrix or on the order the handles were gathered in.
 */

#pragma once

#include <cmath>

#include "BLI_span.hh"

namespace blender::ed::transform {

/**
 * What kind of handle a candidate is.
 *
 * The order is the tie-break order, lowest first. It follows how precisely a handle has to be
 * aimed at: the centre square is a small target sitting where everything meets, an arrow is a line
 * a user follows outwards, a plane diamond is a fixed spot beside it, and a ring is the largest
 * shape of all - it sweeps past every other handle, so it is the one that has to give way. The
 * trackball is last: it is the whole disc behind the manipulator and answers only where nothing
 * else does.
 */
enum class ClarityPickKind {
  Trackball = 0,
  Ring,
  Plane,
  Axis,
  Center,
};

struct ClarityPickCandidate {
  /** Index of the handle this candidate speaks for, negative for "no handle". */
  int handle = -1;
  ClarityPickKind kind = ClarityPickKind::Trackball;
  /** Cursor to the drawn geometry of the handle, in pixels; zero inside a filled shape. */
  float distance_px = 0.0f;
};

/**
 * How far the cursor may sit from a handle and still mean it, in logical pixels.
 *
 * Maya calls this the manipulator Pick Range (`selectPref -manipClickBoxSize`, 8 by default) and
 * gives it to the cursor rather than to the handle: rings and stems are drawn one pixel wide and
 * picked one pixel wide, and what makes them comfortable is this range travelling with the cursor.
 */
constexpr float clarity_pick_range_px = 12.0f;

/**
 * Two handles within this many pixels of each other are equally close, and the kind decides.
 *
 * Without a band the rule would be decided by rounding: a ring and an arrow that cross are a pixel
 * apart in one direction or the other depending on the view angle, and the handle a user gets
 * would follow the orbit rather than the aim.
 */
constexpr float clarity_pick_tie_px = 3.0f;

/** Where one kind of handle stands in the tie-break order. Larger wins. */
constexpr int clarity_pick_kind_rank(const ClarityPickKind kind)
{
  return int(kind);
}

/**
 * The handle the cursor means, or a candidate with a negative handle when it means none.
 *
 * Two passes, so the answer does not depend on the order the candidates arrive in: the nearest
 * distance within range is found first, and the winner is the highest-ranking kind among those
 * that are within #clarity_pick_tie_px of it.
 *
 * The trackball is not part of that contest. It is a disc, not a line, so it is at distance zero
 * everywhere inside itself - and every arrow, ring and plane handle of the manipulator is drawn
 * inside it. Measured against the others it would win the whole manipulator; it is a background,
 * and answers only where nothing else is in range.
 */
inline ClarityPickCandidate clarity_pick_resolve(const Span<ClarityPickCandidate> candidates,
                                                 const float range_px = clarity_pick_range_px,
                                                 const float tie_px = clarity_pick_tie_px)
{
  float nearest = 0.0f;
  bool any = false;
  for (const ClarityPickCandidate &candidate : candidates) {
    if (candidate.handle < 0 || candidate.kind == ClarityPickKind::Trackball ||
        !(candidate.distance_px <= range_px))
    {
      continue;
    }
    if (!any || candidate.distance_px < nearest) {
      nearest = candidate.distance_px;
      any = true;
    }
  }
  if (!any) {
    ClarityPickCandidate background{};
    for (const ClarityPickCandidate &candidate : candidates) {
      if (candidate.handle < 0 || candidate.kind != ClarityPickKind::Trackball ||
          !(candidate.distance_px <= range_px))
      {
        continue;
      }
      if (background.handle < 0 || candidate.distance_px < background.distance_px) {
        background = candidate;
      }
    }
    return background;
  }

  ClarityPickCandidate best{};
  for (const ClarityPickCandidate &candidate : candidates) {
    if (candidate.handle < 0 || candidate.kind == ClarityPickKind::Trackball ||
        !(candidate.distance_px <= nearest + tie_px))
    {
      continue;
    }
    if (best.handle < 0) {
      best = candidate;
      continue;
    }
    const int rank = clarity_pick_kind_rank(candidate.kind);
    const int rank_best = clarity_pick_kind_rank(best.kind);
    if (rank > rank_best || (rank == rank_best && candidate.distance_px < best.distance_px)) {
      best = candidate;
    }
  }
  return best;
}

}  // namespace blender::ed::transform
