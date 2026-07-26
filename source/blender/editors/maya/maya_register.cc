/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include "maya_intern.hh"
#include "maya_tools.hh"

namespace blender::ed::maya {

void register_types()
{
  register_tool_operators();
}

}  // namespace blender::ed::maya

namespace blender {

void ED_operatortypes_maya()
{
  ed::maya::register_types();
}

}  // namespace blender
