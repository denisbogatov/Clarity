/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "clarity_intern.hh"
#include "clarity_marking_menu.hh"
#include "clarity_selection_menu.hh"
#include "clarity_tools.hh"

namespace blender::ed::clarity {

void register_types()
{
  register_tool_operators();
  register_marking_menu_types();
  register_selection_menu_types();
}

}  // namespace blender::ed::clarity

namespace blender {

void ED_operatortypes_clarity()
{
  ed::clarity::register_types();
}

void ED_operatortypes_maya()
{
  ED_operatortypes_clarity();
}

}  // namespace blender
