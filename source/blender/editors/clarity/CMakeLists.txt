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
  clarity_event_dispatch.cc
  clarity_input.cc
  clarity_marking_menu.cc
  clarity_navigation.cc
  clarity_register.cc
  clarity_runtime.cc
  clarity_selection_menu.cc
  clarity_session.cc
  clarity_session_context.cc
  clarity_tool.cc
  clarity_tool_presentation.cc
  clarity_tool_types.cc
  clarity_tools.cc

  clarity_event_dispatch.hh
  clarity_input.hh
  clarity_intern.hh
  clarity_marking_menu.hh
  clarity_navigation.hh
  clarity_runtime.hh
  clarity_selection_menu.hh
  clarity_session.hh
  clarity_session_context.hh
  clarity_tool.hh
  clarity_tool_presentation.hh
  clarity_tools.hh
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

blender_add_lib(bf_editor_clarity "${SRC}" "${INC}" "${INC_SYS}" "${LIB}")

# RNA_prototypes.hh
add_dependencies(bf_editor_clarity bf_rna)

if(WITH_GTESTS)
  set(TEST_SRC
    clarity_runtime_test.cc
    clarity_selection_menu_test.cc
    clarity_topology_select_test.cc
  )
  set(TEST_INC
  )
  set(TEST_LIB
  )
  blender_add_test_suite_lib(editor_clarity "${TEST_SRC}" "${INC};${TEST_INC}" "${INC_SYS}" "${LIB};${TEST_LIB}")
endif()
