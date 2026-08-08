# Clarity test stand on macOS

Two scripts. `setup.sh` prepares the machine once, `go.sh` is the loop you live in afterwards.
Together they are the macOS counterpart of the workspace `go.bat` on Windows, with the same
build options, the same verification and the same test selection.

Apple Silicon only: Blender 5.2 LTS ships no precompiled macOS x86_64 libraries.

## Cloning

The fork is hosted on GitHub, which carries the Git LFS pointers but not the LFS objects - those
live on projects.blender.org. A plain `git clone` therefore dies in the smudge filter with a 404
on the first asset and leaves an incomplete checkout. Skip the smudge, and let `setup.sh` fetch
the files afterwards from a remote that has them:

GitHub also refuses new LFS objects in a fork, because a fork's LFS storage belongs to the parent
repository. This fork's own binary fixtures - the Maya reference captures under
`tests/pivot_reference/fixtures` - therefore stay pointers here and cannot be resolved from
anywhere. Nothing in the build, the tests or the launch touches them, and `setup.sh` reports them
as a warning rather than a failure.

```sh
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/denisbogatov/Clarity.git
```

A clone that already failed this way does not need to be redone; `setup.sh` repairs it.

## Once, after cloning

```sh
chmod +x clarity/mac/*.sh      # only if git did not preserve the executable bit
clarity/mac/setup.sh
```

It checks the machine (architecture, disk, Xcode command line tools), installs `cmake`, `ninja`
and `git-lfs` through Homebrew when they are missing, completes the checkout - adding the LFS
fallback remote, pulling the objects and restoring files a failed clone left missing - and fetches
the precompiled libraries into `lib/macos_arm64` with `make_update.py --no-blender`.

It never touches the checked-out branch, and it restores only files missing from the working tree,
never modified ones, so it stays safe to run again on a machine with work in progress. `--check`
reports without changing anything.

The library download is several gigabytes over Git LFS. If it breaks, run the script again; it
resumes.

## Every day

```sh
clarity/mac/go.sh
```

builds what changed, syncs the Python scripts into the bundle, verifies the tree, starts Blender
and runs the editor and Clarity suites.

| Command | What it does |
| --- | --- |
| `go.sh` | build, verify, launch, run the suites |
| `go.sh --no-tests` | build, verify, launch - the tightest loop |
| `go.sh --no-launch` | build, verify, run the suites |
| `go.sh --tests-only` | run the suites against the tree as it stands |
| `go.sh --python` | a Python-only edit: sync scripts and launch, no native build |
| `go.sh --trace` | foreground session with the manipulator and pivot traces enabled |
| `go.sh --check` | report whether anything is stale; build nothing |
| `go.sh --full` | reconfigure and rebuild from scratch |

The first build compiles the whole tree and takes a long time. Everything after it is
incremental.

## Where things are

| | |
| --- | --- |
| Build tree | `~/ClarityBuild52` |
| Blender | `~/ClarityBuild52/bin/Blender.app` |
| Build log | `~/ClarityBuild52/logs/build-last.log` (plus `.1`, `.2`) |
| Trace logs | `~/ClarityBuild52/logs/` |
| Libraries | `lib/macos_arm64` in the repository |

Nothing is written into the repository, so `git status` stays readable.

## The rules these scripts enforce

One build tree, whose path is fixed in `go.sh` and never discovered by pattern. Build options
live in exactly one place - the configure step in `go.sh` - and the tree stores a hash of the
script, so editing that section is enough to make the next run reconfigure. And nothing is
launched that was not verified: after building, ninja is asked what work is left, and the binary
is compared against its own objects. A tree that is not provably current refuses to start rather
than showing you a program that is not the code on disk.

`go.bat` in the workspace root explains why, at length. Short version: two trees and a dozen
launchers once cost a full day of debugging a viewport whose manipulator could not be clicked,
because the difference was never in the code.

## Differences from the Windows stand

* The Windows-only options are gone: `WITH_WINDOWS_SCCACHE`, the MSVC optimization flags and
  `WITH_CYCLES_CUDA_BINARIES`. Everything else is configured identically, including
  `WITH_UNITY_BUILD=OFF`, `WITH_GTESTS=ON`, `WITH_UI_TESTS=ON` and the assert options.
* Optimization flags are left at CMake's Release defaults for Clang instead of being overridden.
* The Python scripts are synced into `Blender.app/Contents/Resources/<version>/scripts`, and the
  version directory is read from the bundle rather than hardcoded.
* Test-only object files are excluded from the staleness comparison; they are compiled after the
  application links and are not part of it.
