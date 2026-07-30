# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

set(INC
  ../include
  ../../makesrna

  # RNA_prototypes.hh
  ${CMAKE_BINARY_DIR}/source/blender/makesrna
)

set(INC_SYS
)

set(SRC
  maya_event_dispatch.cc
  maya_input.cc
  maya_marking_menu.cc
  maya_navigation.cc
  maya_register.cc
  maya_runtime.cc
  maya_selection_menu.cc
  maya_session.cc
  maya_session_context.cc
  maya_tool.cc
  maya_tool_presentation.cc
  maya_tool_types.cc
  maya_tools.cc

  maya_event_dispatch.hh
  maya_input.hh
  maya_intern.hh
  maya_marking_menu.hh
  maya_navigation.hh
  maya_runtime.hh
  maya_selection_menu.hh
  maya_session.hh
  maya_session_context.hh
  maya_tool.hh
  maya_tool_presentation.hh
  maya_tools.hh
)

set(LIB
  PRIVATE bf::blenkernel
  PRIVATE bf::blenlib
  PRIVATE bf::bmesh
  PRIVATE bf::depsgraph
  PRIVATE bf::dna
  PRIVATE bf::intern::clog
  PRIVATE bf::intern::guardedalloc
  PRIVATE bf::windowmanager
  bf_editor_space_view3d
)

blender_add_lib(bf_editor_maya "${SRC}" "${INC}" "${INC_SYS}" "${LIB}")

# RNA_prototypes.hh
add_dependencies(bf_editor_maya bf_rna)

if(WITH_GTESTS)
  set(TEST_SRC
    maya_runtime_test.cc
    maya_selection_menu_test.cc
  )
  set(TEST_INC
  )
  set(TEST_LIB
  )
  blender_add_test_suite_lib(editor_maya "${TEST_SRC}" "${INC};${TEST_INC}" "${INC_SYS}" "${LIB};${TEST_LIB}")
endif()
