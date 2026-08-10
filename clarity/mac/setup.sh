#!/usr/bin/env bash
# =============================================================================================
#  Prepares the macOS test stand for this fork: toolchain, precompiled libraries, sanity checks.
#
#  Run this once after cloning. Everything after it is `clarity/mac/go.sh`.
#
#  Usage:
#    clarity/mac/setup.sh          check the machine, install what is missing, fetch the libs
#    clarity/mac/setup.sh --check  report only; install and download nothing
#    clarity/mac/setup.sh --yes    do not ask before installing Homebrew packages
#    clarity/mac/setup.sh --help
#
#  What it does not do: it never touches the checked-out branch. The libraries are fetched with
#  `make_update.py --no-blender`, so local commits and uncommitted work are left alone.
# =============================================================================================

set -u
set -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
LIB_DIR="${SOURCE_DIR}/lib/macos_arm64"
BUILD_DIR="${HOME}/ClarityBuild52"

CHECK_ONLY=0
ASSUME_YES=0
PROBLEMS=0

say() { printf '%s\n' "$*"; }
err() { printf '%s\n' "$*" >&2; }
stage() { printf '\n=== %s ===\n' "$*"; }
ok() { printf '  [ok]   %s\n' "$*"; }
warn() { printf '  [warn] %s\n' "$*"; }
bad() { printf '  [FAIL] %s\n' "$*" >&2; PROBLEMS=$((PROBLEMS + 1)); }

usage() {
  cat <<'EOF'
Usage: clarity/mac/setup.sh [options]

  (no options)   check the machine, install what is missing, fetch the precompiled libraries
  --check        report only; install and download nothing
  --yes          do not ask before installing Homebrew packages
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --check)   CHECK_ONLY=1 ;;
    --yes|-y)  ASSUME_YES=1 ;;
    --help|-h) usage; exit 2 ;;
    *) err "[ERROR] Unknown argument: $1"; err ""; usage >&2; exit 2 ;;
  esac
  shift
done

confirm() {
  local answer
  [ "${ASSUME_YES}" = "1" ] && return 0
  [ -t 0 ] || return 1
  printf '%s [y/N] ' "$1"
  read -r answer
  case "${answer}" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}


# ---------------------------------------------------------------------------------------------
#  The machine
# ---------------------------------------------------------------------------------------------
stage "Machine"

if [ "$(uname -s)" != "Darwin" ]; then
  err "[ERROR] This script prepares the macOS stand. On Windows use go.bat."
  exit 1
fi
ok "macOS $(sw_vers -productVersion)"

case "$(sw_vers -productVersion)" in
  10.*|11.0|11.1) warn "Blender 5.2 targets macOS 11.2 and newer; this system is older." ;;
esac

if [ "$(uname -m)" != "arm64" ]; then
  bad "Architecture $(uname -m): Blender 5.2 LTS ships no precompiled macOS x86_64 libraries."
  err ""
  err "        Only Apple Silicon is supported by this stand. If this is an arm64 Mac, the"
  err "        shell is running under Rosetta - open a native terminal and run this again."
  exit 1
fi
ok "Apple Silicon (arm64)"

# The tree, libraries and the persistent compiler cache together can use close to 90 GB.
FREE_GB="$(df -g "${HOME}" 2>/dev/null | awk 'NR==2 {print $4}')"
if [ -n "${FREE_GB:-}" ]; then
  if [ "${FREE_GB}" -lt 90 ]; then
    warn "${FREE_GB} GB free on ${HOME}; build, libraries and ccache can use about 90 GB."
  else
    ok "${FREE_GB} GB free on ${HOME}"
  fi
fi


# ---------------------------------------------------------------------------------------------
#  Toolchain
# ---------------------------------------------------------------------------------------------
stage "Toolchain"

if xcode-select --print-path >/dev/null 2>&1; then
  ok "Command line tools at $(xcode-select --print-path)"
else
  if [ "${CHECK_ONLY}" = "1" ]; then
    bad "The Xcode command line tools are not installed (xcode-select --install)."
  else
    say "  Installing the Xcode command line tools; a system dialog will open."
    xcode-select --install >/dev/null 2>&1 || true
    err ""
    err "[ERROR] Finish the command line tools installation, then run this script again."
    exit 1
  fi
fi

# A double-clicked script or a non-login shell does not always have Homebrew on PATH.
[ -d /opt/homebrew/bin ] && PATH="/opt/homebrew/bin:${PATH}"
export PATH

MISSING=""
for tool in cmake ninja ccache git-lfs; do
  case "${tool}" in
    git-lfs) command -v git-lfs >/dev/null 2>&1 && { ok "git-lfs $(git lfs version 2>/dev/null | awk '{print $1}')"; continue ;} ;;
    *) command -v "${tool}" >/dev/null 2>&1 && { ok "${tool} $("${tool}" --version 2>/dev/null | head -1)"; continue ;} ;;
  esac
  MISSING="${MISSING} ${tool}"
done

for tool in git python3 rsync; do
  if command -v "${tool}" >/dev/null 2>&1; then
    ok "${tool} $(command -v "${tool}")"
  else
    bad "${tool} was not found; it normally comes with the command line tools."
  fi
done

if [ -n "${MISSING# }" ]; then
  if [ "${CHECK_ONLY}" = "1" ]; then
    bad "Missing build tools:${MISSING}"
  elif ! command -v brew >/dev/null 2>&1; then
    bad "Missing build tools:${MISSING} - and Homebrew was not found."
    err ""
    err "        Install Homebrew from https://brew.sh and run this script again, or install"
    err "        cmake, ninja, ccache and git-lfs some other way."
    exit 1
  else
    say "  Missing build tools:${MISSING}"
    if confirm "  Install them with: brew install${MISSING} ?"; then
      # shellcheck disable=SC2086
      if ! brew install ${MISSING}; then
        err "[ERROR] brew install failed."
        exit 1
      fi
      for tool in ${MISSING}; do
        command -v "${tool}" >/dev/null 2>&1 || bad "${tool} is still not on PATH after installation."
      done
    else
      bad "Missing build tools:${MISSING}"
    fi
  fi
fi

# An Intel Homebrew installation in /usr/local can run through Rosetta on Apple Silicon. CMake
# then reports x86_64 as the host processor even when -arch arm64 is requested, and Blender adds
# the incompatible -march=x86-64-v2 flag. Refuse that toolchain before it can poison the cache.
if command -v cmake >/dev/null 2>&1; then
  CMAKE_HOST_PROCESSOR="$(cmake --system-information 2>/dev/null |
    awk -F '"' '/^CMAKE_HOST_SYSTEM_PROCESSOR / {print $2; exit}')"
  if [ "${CMAKE_HOST_PROCESSOR}" != "arm64" ]; then
    bad "cmake $(command -v cmake) reports ${CMAKE_HOST_PROCESSOR:-an unknown architecture}, not arm64."
    err ""
    err "        Install native Apple Silicon Homebrew in /opt/homebrew, then run:"
    err "        /opt/homebrew/bin/brew install cmake ninja ccache git-lfs"
  else
    ok "cmake host architecture arm64"
  fi
fi

# Ninja is copied into the build tree by go.sh so Homebrew upgrades cannot silently change its
# .ninja_log format. Ccache is the second line of defense if a deliberate toolchain migration ever
# makes a broad rebuild unavoidable. Both must be native; Rosetta tools can come from /usr/local
# even in an otherwise arm64 shell.
for tool in ninja ccache; do
  if command -v "${tool}" >/dev/null 2>&1; then
    TOOL_PATH="$(command -v "${tool}")"
    if file "${TOOL_PATH}" 2>/dev/null | grep -q 'arm64'; then
      ok "${tool} is native arm64 (${TOOL_PATH})"
    else
      bad "${tool} ${TOOL_PATH} is not a native arm64 executable."
      err ""
      err "        Install it with native Homebrew: /opt/homebrew/bin/brew install ${tool}"
    fi
  fi
done


# ---------------------------------------------------------------------------------------------
#  Repository and precompiled libraries
#
#  Blender is not built from source alone: every dependency comes precompiled from a Git LFS
#  submodule for the platform. `make_update.py` enables the submodule for this platform, sets up
#  the LFS fallback remote a GitHub fork needs, and pulls the files. `--no-blender` keeps it away
#  from the working branch.
# ---------------------------------------------------------------------------------------------
stage "Repository"

if [ ! -d "${SOURCE_DIR}/.git" ]; then
  err "[ERROR] The Clarity repository was not found at ${SOURCE_DIR}."
  exit 1
fi
ok "Repository ${SOURCE_DIR}"
ok "Branch $(git -C "${SOURCE_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null)"

case "${SOURCE_DIR}" in
  *\ *) warn "The path contains spaces. Blender builds are usually fine with that, but a build
         system that mishandles one fails in confusing ways; a space-free path is safer." ;;
esac

if [ "${PROBLEMS}" -ne 0 ]; then
  err ""
  err "[ERROR] Fix the problems above before fetching the libraries."
  exit 1
fi


# ---------------------------------------------------------------------------------------------
#  Working tree
#
#  A fork hosted on GitHub carries the LFS pointers but usually not the LFS objects: those live on
#  projects.blender.org. The clone then dies in the smudge filter with a 404 on the first asset and
#  leaves an incomplete checkout - files present in the index but missing on disk. LFS is told to
#  search every remote and given upstream Blender as one, which is where the objects are.
# ---------------------------------------------------------------------------------------------
stage "Working tree"

DELETED_COUNT="$(git -C "${SOURCE_DIR}" ls-files --deleted 2>/dev/null | wc -l | tr -d ' ')"
POINTER_COUNT="$(git -C "${SOURCE_DIR}" lfs ls-files 2>/dev/null | grep -c ' - ' | tr -d ' ')"

if [ "${CHECK_ONLY}" = "1" ]; then
  if [ "${DELETED_COUNT}" = "0" ] && [ "${POINTER_COUNT}" = "0" ]; then
    ok "Checkout is complete"
  else
    bad "Incomplete checkout: ${DELETED_COUNT} missing file(s), ${POINTER_COUNT} unresolved LFS pointer(s)."
  fi
else
  git -C "${SOURCE_DIR}" config lfs.remote.searchall true
  # GitHub refuses new LFS objects in a fork - its storage belongs to the parent repository - so
  # this fork's own binary fixtures exist as pointers that no remote can resolve. Without this a
  # checkout aborts on the first one; with it the pointer is written instead and work continues.
  git -C "${SOURCE_DIR}" config lfs.skipdownloaderrors true
  if git -C "${SOURCE_DIR}" remote get-url lfs-fallback >/dev/null 2>&1; then
    ok "LFS fallback remote already configured"
  else
    say "  Adding the LFS fallback remote (projects.blender.org)."
    git -C "${SOURCE_DIR}" remote add lfs-fallback https://projects.blender.org/blender/blender.git
    git -C "${SOURCE_DIR}" remote set-url --push lfs-fallback no_push
  fi

  if [ "${DELETED_COUNT}" != "0" ] || [ "${POINTER_COUNT}" != "0" ]; then
    say "  ${DELETED_COUNT} missing file(s), ${POINTER_COUNT} unresolved LFS pointer(s); repairing."
  fi
  if ! git -C "${SOURCE_DIR}" lfs pull; then
    bad "git lfs pull failed. The objects were not found on any remote."
  fi
  # Only files missing from the working tree are restored. Modified files are never touched: this
  # script must be safe to run again on a machine with work in progress.
  if [ "${DELETED_COUNT}" != "0" ]; then
    git -C "${SOURCE_DIR}" ls-files -z --deleted | \
      (cd "${SOURCE_DIR}" && xargs -0 git restore --source=HEAD --)
  fi

  DELETED_COUNT="$(git -C "${SOURCE_DIR}" ls-files --deleted 2>/dev/null | wc -l | tr -d ' ')"
  POINTER_COUNT="$(git -C "${SOURCE_DIR}" lfs ls-files 2>/dev/null | grep -c ' - ' | tr -d ' ')"
  if [ "${DELETED_COUNT}" != "0" ]; then
    bad "${DELETED_COUNT} file(s) are still missing from the working tree."
  fi
  if [ "${POINTER_COUNT}" != "0" ]; then
    # Not a failure: nothing under the reference fixtures is compiled, tested or launched. Those
    # captures are compared against Autodesk Maya, which only exists on the Windows machine.
    warn "${POINTER_COUNT} file(s) are unresolved LFS pointers - their objects exist on no remote."
    git -C "${SOURCE_DIR}" lfs ls-files 2>/dev/null | grep ' - ' | awk '{print "         " $3}' | head -5
    say "         The build does not use them; only the Maya reference comparison does."
  fi
  if [ "${DELETED_COUNT}" = "0" ] && [ "${POINTER_COUNT}" = "0" ]; then
    ok "Checkout is complete"
  fi
fi

if [ "${PROBLEMS}" -ne 0 ]; then
  err ""
  err "[ERROR] Fix the problems above before fetching the libraries."
  exit 1
fi

stage "Precompiled libraries"

LIB_READY=0
if [ -d "${LIB_DIR}" ] && [ "$(ls -A "${LIB_DIR}" 2>/dev/null | wc -l | tr -d ' ')" -gt 5 ]; then
  LIB_READY=1
fi

if [ "${CHECK_ONLY}" = "1" ]; then
  if [ "${LIB_READY}" = "1" ]; then
    ok "Present at ${LIB_DIR}"
  else
    bad "Missing at ${LIB_DIR} (run this script without --check)."
  fi
else
  if [ "${LIB_READY}" = "1" ]; then
    ok "Present at ${LIB_DIR}"
    say "  Checking them against the branch anyway; this is cheap when nothing changed."
  fi
  if ! (cd "${SOURCE_DIR}" && git lfs install --skip-repo); then
    err "[ERROR] git lfs install failed."
    exit 1
  fi
  if ! (cd "${SOURCE_DIR}" && python3 build_files/utils/make_update.py --no-blender); then
    err ""
    err "[ERROR] Fetching the precompiled libraries failed. It is a large download over Git LFS;"
    err "        running this script again resumes it."
    exit 1
  fi
  if [ -d "${LIB_DIR}" ] && [ "$(ls -A "${LIB_DIR}" 2>/dev/null | wc -l | tr -d ' ')" -gt 5 ]; then
    ok "Fetched into ${LIB_DIR}"
  else
    bad "The library directory is still empty: ${LIB_DIR}"
  fi
fi

# An LFS checkout that did not resolve leaves pointer files: a few hundred bytes of text where a
# static library should be. Some legitimate stub archives are also that small, so check the LFS
# signature instead of treating every small archive as a pointer.
if [ -d "${LIB_DIR}" ]; then
  POINTERS="$(find "${LIB_DIR}" -type f -name '*.a' -size -2k \
    -exec grep -Ilx 'version https://git-lfs.github.com/spec/v1' {} + 2>/dev/null | head -3)"
  if [ -n "${POINTERS}" ]; then
    bad "Some libraries are unresolved Git LFS pointers, for example:"
    printf '         %s\n' ${POINTERS} >&2
    err "         Run: git -C \"${SOURCE_DIR}\" lfs pull"
  else
    ok "Libraries are real files, not LFS pointers"
  fi
fi


# ---------------------------------------------------------------------------------------------
#  Verdict
# ---------------------------------------------------------------------------------------------
stage "Result"

if [ "${PROBLEMS}" -ne 0 ]; then
  err "The stand is NOT ready: ${PROBLEMS} problem(s) above."
  exit 1
fi

say "The stand is ready."
say ""
say "  Build tree:  ${BUILD_DIR}   (created by the first build)"
say "  Next:        clarity/mac/go.sh --no-tests"
say ""
say "The first build compiles the whole tree and warms ccache. Every build after it only compiles"
say "what changed; even an intentional toolchain migration can reuse cached compiler results."
say "go.sh --help lists the rest."
exit 0
