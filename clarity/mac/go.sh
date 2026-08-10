#!/usr/bin/env bash
# =============================================================================================
#  The single entry point for the macOS test stand. One build tree, one script.
#
#  Usage:
#    clarity/mac/go.sh                 build what changed, verify, launch, run the suites
#    clarity/mac/go.sh --no-tests      build, verify, launch
#    clarity/mac/go.sh --no-launch     build, verify, run tests
#    clarity/mac/go.sh --check         report whether anything is stale; build nothing
#    clarity/mac/go.sh --tests-only    run the suites against the current tree
#    clarity/mac/go.sh --python        sync Python scripts only, then launch (no native build)
#    clarity/mac/go.sh --trace         build, then run with the manipulator and pivot traces on
#    clarity/mac/go.sh --full          reconfigure and rebuild the tree from scratch
#    clarity/mac/go.sh --help
#
#  This is the macOS counterpart of the workspace `go.bat`, and it keeps the same three rules:
#
#   1. One tree. Nothing here searches for a build; the path is fixed below.
#   2. Options live in one place - the configure step in this file. The tree records a hash of
#      this script and reconfigures itself whenever the file changes, so editing options is
#      enough.
#   3. Never launch what was not verified. After building, ninja is asked what work is left; if
#      any remains, or the executable is older than its own objects, Blender is not started.
#
#  The reason for those rules is written down in `go.bat`: this workspace once had two build
#  trees and a dozen launchers, the same sources produced two programs that behaved
#  differently, and the binary that started was not necessarily the one just built.
# =============================================================================================

set -u
set -o pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${SCRIPT_PATH}")" && pwd)"
SOURCE_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

# The one build tree. Deliberately outside the source directory and never discovered by pattern.
BUILD_DIR="${HOME}/ClarityBuild52"

BLENDER_APP="${BUILD_DIR}/bin/Blender.app"
BLENDER_BIN="${BLENDER_APP}/Contents/MacOS/Blender"
LOG_DIR="${BUILD_DIR}/logs"
BUILD_LOG="${LOG_DIR}/build-last.log"
CONFIG_STAMP="${BUILD_DIR}/.go-config.stamp"
LIB_DIR="${SOURCE_DIR}/lib/macos_arm64"
NINJA_BIN=""

DO_TESTS=1
DO_LAUNCH=1
DO_BUILD=1
CHECK_ONLY=0
DO_TRACE=0
FULL_REBUILD=0
PYTHON_ONLY=0

say() { printf '%s\n' "$*"; }
err() { printf '%s\n' "$*" >&2; }

usage() {
  cat <<'EOF'
Usage: clarity/mac/go.sh [options]

  (no options)   build what changed, verify, launch, run the editor and Clarity suites
  --no-tests     build, verify, launch
  --no-launch    build, verify, run tests
  --check        report whether anything is stale; build nothing
  --tests-only   run the suites against the current tree
  --python       sync Python scripts only, then launch
  --trace        build, then run with manipulator and pivot traces enabled
  --full         reconfigure and rebuild from scratch
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --no-tests)   DO_TESTS=0 ;;
    --no-launch)  DO_LAUNCH=0 ;;
    --check)      CHECK_ONLY=1 ;;
    --tests-only) DO_BUILD=0; DO_LAUNCH=0 ;;
    --python)     PYTHON_ONLY=1; DO_TESTS=0 ;;
    --trace)      DO_TRACE=1; DO_TESTS=0 ;;
    --full)       FULL_REBUILD=1 ;;
    --help|-h)    usage; exit 2 ;;
    *)
      err "[ERROR] Unknown argument: $1"
      err ""
      usage >&2
      exit 2
      ;;
  esac
  shift
done


# ---------------------------------------------------------------------------------------------
#  Environment
# ---------------------------------------------------------------------------------------------
setup_environment() {
  local cmake_host_processor

  if [ "$(uname -s)" != "Darwin" ]; then
    err "[ERROR] This script is the macOS stand. On Windows use go.bat."
    return 1
  fi
  if [ "$(uname -m)" != "arm64" ]; then
    err "[ERROR] This tree builds for Apple Silicon only: Blender 5.2 LTS ships no precompiled"
    err "        macOS x86_64 libraries. Detected architecture: $(uname -m)."
    err "        If this is an arm64 Mac, the shell is running under Rosetta; open a native one."
    return 1
  fi

  # A double-clicked script or a non-login shell does not always have Homebrew on PATH.
  [ -d /opt/homebrew/bin ] && PATH="/opt/homebrew/bin:${PATH}"
  export PATH

  if ! xcode-select --print-path >/dev/null 2>&1; then
    err "[ERROR] The Xcode command line tools are not installed. Run clarity/mac/setup.sh."
    return 1
  fi
  for tool in cmake ninja git rsync; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
      err "[ERROR] ${tool} was not found on PATH. Run clarity/mac/setup.sh."
      return 1
    fi
  done
  # Keep one Ninja executable for the entire run. Ninja 1.11 and 1.13 use incompatible build-log
  # formats; alternating between /usr/local and /opt/homebrew makes each version discard the
  # other's log and rebuild the whole tree.
  NINJA_BIN="$(command -v ninja)"
  cmake_host_processor="$(cmake --system-information 2>/dev/null |
    awk -F '"' '/^CMAKE_HOST_SYSTEM_PROCESSOR / {print $2; exit}')"
  if [ "${cmake_host_processor}" != "arm64" ]; then
    err "[ERROR] cmake $(command -v cmake) reports ${cmake_host_processor:-an unknown architecture},"
    err "        not arm64. Run clarity/mac/setup.sh after installing native Homebrew in"
    err "        /opt/homebrew. The Intel /usr/local toolchain creates an invalid build cache."
    return 1
  fi
  if [ ! -d "${SOURCE_DIR}/.git" ]; then
    err "[ERROR] The Clarity repository was not found at ${SOURCE_DIR}."
    return 1
  fi
  # Without the precompiled libraries CMake fails halfway through configuration and leaves a
  # half-written cache behind, which then has to be deleted by hand. Refuse before that.
  if [ ! -d "${LIB_DIR}" ] || [ -z "$(ls -A "${LIB_DIR}" 2>/dev/null)" ]; then
    err "[ERROR] The precompiled libraries are missing: ${LIB_DIR}"
    err "        Run clarity/mac/setup.sh - it fetches them through the lib submodule."
    return 1
  fi
  mkdir -p "${LOG_DIR}" || return 1
  return 0
}


# ---------------------------------------------------------------------------------------------
#  Configure
#
#  Build options live here and nowhere else. The rule for this section:
#
#      Only turn something off when it cannot change the program - only how long it takes to
#      build.
#
#  WITH_* options become preprocessor defines, and a define can change which fields a struct
#  has. So features stay on; only build info and caching tricks are traded away. These are the
#  same options the Windows tree is configured with, minus the ones that only exist there.
# ---------------------------------------------------------------------------------------------
config_hash() {
  sed -n '/^  # CONFIG_HASH_BEGIN$/,/^  # CONFIG_HASH_END$/p' "${SCRIPT_PATH}" 2>/dev/null |
    shasum -a 256 | awk '{print $1}'
}

configure_if_needed() {
  local hash stamped expected_home
  local -a configure_args

  # CONFIG_HASH_BEGIN
  configure_args=(
    -C "${SOURCE_DIR}/build_files/cmake/config/blender_release.cmake"
    -S "${SOURCE_DIR}"
    -B "${BUILD_DIR}"
    -G Ninja
    -DCMAKE_BUILD_TYPE=Release
    -DCMAKE_OSX_ARCHITECTURES=arm64
    -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
    -DWITH_UNITY_BUILD=OFF
    -DWITH_COMPILER_PRECOMPILED_HEADERS=ON
    -DWITH_BUILDINFO=OFF
    -DWITH_GTESTS=ON
    -DWITH_UI_TESTS=ON
    -DWITH_ASSERT_ABORT=ON
    -DWITH_ASSERT_RELEASE=ON
  )
  # CONFIG_HASH_END

  hash="$(config_hash)"
  if [ -z "${hash}" ]; then
    err "[ERROR] Could not hash this script to check the build configuration."
    return 1
  fi

  # A generated tree records the source directory it belongs to, and CMake refuses to retarget
  # one. If that path is not ours, the cache has to be regenerated rather than reused.
  if [ -f "${BUILD_DIR}/CMakeCache.txt" ]; then
    expected_home="CMAKE_HOME_DIRECTORY:INTERNAL=${SOURCE_DIR}"
    if ! grep -qxF "${expected_home}" "${BUILD_DIR}/CMakeCache.txt"; then
      say "[GO] This tree was generated for a different source path; regenerating it from scratch."
      rm -f "${BUILD_DIR}/CMakeCache.txt" "${CONFIG_STAMP}"
      rm -rf "${BUILD_DIR}/CMakeFiles"
    fi
  fi

  if [ -f "${BUILD_DIR}/build.ninja" ] && [ -f "${CONFIG_STAMP}" ]; then
    stamped="$(cat "${CONFIG_STAMP}" 2>/dev/null)"
    if [ "${stamped}" = "${hash}" ]; then
      return 0
    fi
    say "[GO] Build options changed since this tree was configured; reconfiguring."
  fi

  say "=== Configure ==="
  mkdir -p "${BUILD_DIR}" || return 1
  if ! cmake "${configure_args[@]}"; then
    err "[ERROR] CMake configuration failed. Nothing was built."
    return 1
  fi
  if [ ! -f "${BUILD_DIR}/build.ninja" ]; then
    err "[ERROR] Configuration produced no build.ninja."
    return 1
  fi
  printf '%s\n' "${hash}" > "${CONFIG_STAMP}"
  return 0
}


# ---------------------------------------------------------------------------------------------
#  Build
# ---------------------------------------------------------------------------------------------
close_blender() {
  local pids pid path ours waited
  ours=""
  pids="$(pgrep -x Blender 2>/dev/null || true)"
  for pid in ${pids}; do
    # Only the Blender built in this tree is closed; another Blender the user happens to be
    # running is none of this script's business.
    path="$(ps -p "${pid}" -o comm= 2>/dev/null || true)"
    if [ "${path}" = "${BLENDER_BIN}" ]; then
      ours="${ours:+${ours},}${pid}"
    fi
  done
  [ -z "${ours}" ] && return 0

  say "[GO] Closing the running Blender from this tree (unsaved work in it is lost)..."
  for pid in ${ours//,/ }; do
    kill -TERM "${pid}" 2>/dev/null || true
  done
  waited=0
  while [ ${waited} -lt 120 ]; do
    if ! ps -p "${ours}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  err "[ERROR] Blender is still running. Close it and run go.sh again."
  return 1
}

rotate_build_log() {
  [ -f "${BUILD_LOG}.1" ] && mv -f "${BUILD_LOG}.1" "${BUILD_LOG}.2"
  [ -f "${BUILD_LOG}" ] && mv -f "${BUILD_LOG}" "${BUILD_LOG}.1"
  return 0
}

build() {
  local status diagnostics
  close_blender || return 1
  rotate_build_log
  say "=== Build ==="
  NINJA_STATUS='[%f/%t %es, %r running] ' "${NINJA_BIN}" -C "${BUILD_DIR}" 2>&1 |
    tee "${BUILD_LOG}"
  status="${PIPESTATUS[0]}"
  if [ "${status}" -ne 0 ]; then
    say ""
    say "=== RESULT: BUILD FAILED ==="
    if [ -f "${BUILD_LOG}" ]; then
      say "--- from build-last.log ---"
      diagnostics="$(grep -E '^FAILED: |error: |ld: |Undefined symbols|ninja: build stopped' "${BUILD_LOG}" | head -40)"
      if [ -n "${diagnostics}" ]; then
        printf '%s\n' "${diagnostics}"
      else
        say "  (no compiler diagnostic matched; the failure is earlier in the log)"
      fi
      say "---------------------------"
      say "Full output: ${BUILD_LOG}"
    fi
    say ""
    say "Blender was NOT started: the executable would not be the code on disk."
    return 1
  fi
  return 0
}


# ---------------------------------------------------------------------------------------------
#  Bundle
#
#  Ninja links the application, while CMake's install phase copies the precompiled shared
#  libraries and runtime data into Blender.app. Without this step the executable links
#  successfully but cannot start because @rpath libraries such as liboslexec.dylib are absent.
# ---------------------------------------------------------------------------------------------
install_bundle() {
  say "=== Install bundle ==="
  if ! cmake --install "${BUILD_DIR}" >/dev/null; then
    err "[ERROR] CMake could not install the runtime files into Blender.app."
    return 1
  fi
  return 0
}


# ---------------------------------------------------------------------------------------------
#  Python scripts
#
#  Python is not cosmetic in this fork: keymaps, the tool system and the viewport UI live in it.
#  Scripts and executable drifting apart produce behaviour matching neither, which reads as a C++
#  bug - a keyconfig left over from an older build once did exactly that.
# ---------------------------------------------------------------------------------------------
python_target() {
  # The version directory is read from the bundle rather than hardcoded, so a version bump does
  # not silently stop the sync.
  local resources dir
  resources="${BLENDER_APP}/Contents/Resources"
  [ -d "${resources}" ] || return 0
  for dir in "${resources}"/[0-9]*.[0-9]*; do
    if [ -d "${dir}/scripts" ]; then
      printf '%s\n' "${dir}/scripts"
      return 0
    fi
  done
  return 0
}

sync_python() {
  local target
  target="$(python_target)"
  [ -z "${target}" ] && return 0
  if ! rsync -a "${SOURCE_DIR}/scripts/" "${target}/"; then
    err "[ERROR] Python script sync failed."
    return 1
  fi
  return 0
}


# ---------------------------------------------------------------------------------------------
#  Verify - the reason a stale binary cannot be launched any more
# ---------------------------------------------------------------------------------------------
verify_tree() {
  local pending
  if [ ! -f "${BUILD_DIR}/build.ninja" ]; then
    err "[ERROR] The build tree is not configured."
    return 1
  fi
  if [ ! -x "${BLENDER_BIN}" ]; then
    err "[ERROR] The Blender binary does not exist: ${BLENDER_BIN}"
    return 1
  fi
  if ! pending="$("${NINJA_BIN}" -C "${BUILD_DIR}" -n 2>/dev/null)"; then
    err "[ERROR] ninja cannot evaluate this tree; it may be damaged. Run go.sh --full."
    return 1
  fi
  # Match ninja's own "no work to do" rather than counting lines: with -C it also prints
  # "Entering directory", so a clean tree emits two lines.
  if ! printf '%s\n' "${pending}" | grep -q 'no work to do'; then
    err "[ERROR] The tree is NOT up to date - ninja still has work left:"
    printf '%s\n' "${pending}" | grep '^\[' | head -20 >&2
    err "[ERROR] Blender was not started. Run go.sh again; if this repeats, run go.sh --full."
    return 1
  fi
  # Ninja's dependency graph is authoritative. Comparing the executable timestamp with every
  # object in the tree is invalid: shader and utility targets are independent of the Blender
  # link and can legitimately finish one second later.
  say "[GO] Verified: tree up to date, the binary matches the sources and the configuration."
  return 0
}


# ---------------------------------------------------------------------------------------------
#  Launch
# ---------------------------------------------------------------------------------------------
launch() {
  if [ ! -x "${BLENDER_BIN}" ]; then
    err "[ERROR] The Blender binary does not exist: ${BLENDER_BIN}"
    return 1
  fi
  export BLENDER_STARTUP_TRACE_FILE="${LOG_DIR}/blender-startup-trace.log"
  if [ "${DO_TRACE}" = "1" ]; then
    # A trace session owns the terminal: stderr carries the manipulator trace, so Blender runs
    # in the foreground until the problem has been reproduced and the editor closed.
    export BLENDER_CLARITY_GIZMO_TRACE=1
    export BLENDER_CLARITY_SNAP_TRACE_FILE="${LOG_DIR}/clarity-snap-trace.log"
    rm -f "${BLENDER_CLARITY_SNAP_TRACE_FILE}"
    say "=== Trace session ==="
    say "Reproduce the problem, then close Blender. Logs:"
    say "  ${LOG_DIR}/blender-startup-trace.log"
    say "  ${LOG_DIR}/gizmo-trace.log"
    say "  ${LOG_DIR}/clarity-snap-trace.log"
    say ""
    "${BLENDER_BIN}" 2>"${LOG_DIR}/gizmo-trace.log"
  else
    # Detailed pivot and gizmo traces stay off here: they put synchronous file writes directly
    # in the modal interaction path, which is the last place to add latency.
    unset BLENDER_CLARITY_GIZMO_TRACE
    unset BLENDER_CLARITY_SNAP_TRACE_FILE
    say "=== Start Blender ==="
    # The binary inside the bundle is started directly rather than through `open`, because
    # `open` hands the app a fresh environment and the startup trace variable would be lost.
    nohup "${BLENDER_BIN}" >"${LOG_DIR}/blender-session.log" 2>&1 &
    disown
  fi
  return 0
}


# ---------------------------------------------------------------------------------------------
#  Tests
# ---------------------------------------------------------------------------------------------
run_tests() {
  say "=== Tests ==="
  # The gtest runner is kept out of the default build so normal iteration does not pay for it.
  if ! "${NINJA_BIN}" -C "${BUILD_DIR}" blender_test; then
    err "[ERROR] The test runner failed to build."
    return 1
  fi
  # ctest hands each suite the environment the build system defines for it. Starting
  # blender_test by hand fails on a missing library before running a single test.
  #
  # The `ui_opengl_test_clarity_pivot.*` suites are event-simulation tests: they start Blender
  # with a real window, so they need the tree to be built, not just the gtest runner. Only the
  # Clarity ones are selected - WITH_UI_TESTS registers the whole upstream set as well.
  ctest --test-dir "${BUILD_DIR}" \
    -R '^(editor_.*|clarity_interaction_defaults|clarity_pivot_lifecycle|ui_opengl_test_clarity_pivot\..*)$' \
    --output-on-failure \
    --parallel "$(sysctl -n hw.ncpu)"
}


# ---------------------------------------------------------------------------------------------
#  Reporting
# ---------------------------------------------------------------------------------------------
report_state() {
  local stamped hash
  say "=== State ==="
  say "Build tree:  ${BUILD_DIR}"
  if [ -x "${BLENDER_BIN}" ]; then
    say "Blender:     $(stat -f '%Sm' -t '%Y-%m-%d %H:%M:%S' "${BLENDER_BIN}")"
  else
    say "Blender:     missing"
  fi
  hash="$(config_hash)"
  stamped=""
  [ -f "${CONFIG_STAMP}" ] && stamped="$(cat "${CONFIG_STAMP}")"
  if [ -n "${hash}" ] && [ "${stamped}" = "${hash}" ]; then
    say "Config:      matches this script"
  else
    say "Config:      OUT OF DATE - go.sh will reconfigure"
  fi
  if [ -f "${BUILD_DIR}/build.ninja" ]; then
    if "${NINJA_BIN}" -C "${BUILD_DIR}" -n 2>/dev/null | grep -q 'no work to do'; then
      say "Tree:        up to date"
    else
      say "Tree:        stale, work pending"
    fi
  else
    say "Tree:        not configured"
  fi
  return 0
}


# ---------------------------------------------------------------------------------------------
#  Flow
# ---------------------------------------------------------------------------------------------
setup_environment || exit 1

if [ "${CHECK_ONLY}" = "1" ]; then
  report_state
  exit 0
fi

if [ "${PYTHON_ONLY}" = "1" ]; then
  sync_python || exit 1
  verify_tree || exit 1
  launch || exit 1
  say ""
  say "=== RESULT: Python scripts synced; Blender started. ==="
  exit 0
fi

if [ "${FULL_REBUILD}" = "1" ]; then
  say "=== Full rebuild ==="
  [ -f "${BUILD_DIR}/build.ninja" ] &&
    "${NINJA_BIN}" -C "${BUILD_DIR}" -t clean >/dev/null 2>&1
  rm -f "${CONFIG_STAMP}"
fi

if [ "${DO_BUILD}" = "1" ]; then
  configure_if_needed || exit 1
  build || exit 1
  install_bundle || exit 1
  sync_python || exit 1
  verify_tree || exit 1
fi

if [ "${DO_LAUNCH}" = "1" ]; then
  launch || exit 1
fi

if [ "${DO_TESTS}" = "0" ]; then
  say ""
  say "=== RESULT: build and verification passed; tests skipped. ==="
  exit 0
fi

if ! run_tests; then
  say ""
  say "=== RESULT: build passed, TESTS FAILED. ==="
  exit 1
fi

say ""
say "=== RESULT: build, verification and tests passed. ==="
exit 0
