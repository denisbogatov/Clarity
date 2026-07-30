/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_intern.hh"
#include "maya_marking_menu.hh"
#include "maya_selection_menu.hh"
#include "maya_tools.hh"

namespace blender::ed::maya {

void register_types()
{
  register_tool_operators();
  register_marking_menu_types();
  register_selection_menu_types();
}

}  // namespace blender::ed::maya

namespace blender {

void ED_operatortypes_maya()
{
  ed::maya::register_types();
}

}  // namespace blender
