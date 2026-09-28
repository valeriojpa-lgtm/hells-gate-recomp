DANTE'S INFERNO - RUN 00 PORTABLE BUILDER

Place this pack in the ROOT of your hells-gate-recomp source folder.
The root must contain CMakeLists.txt, setup.ps1, patches\ and game\.

Required game files in game\:
  default.xex
  default.xexp
  bigfile0.viv
  bigfile1.viv

Then double-click BUILD_DANTE_PORTABLE.cmd.

The builder downloads these into .portable\ only:
  MinGit 2.55.0.5
  CMake 4.4.3
  Ninja 1.13.2
  Python 3.12.10 embeddable
  LLVM/Clang 20.1.8

It clones ReXGlue SDK v0.10.0 (including submodules), applies Hell's Gate's
existing SDK patch, regenerates C++ from YOUR default.xex, applies the existing
generated-code patch and builds a fresh Windows D3D12 executable.

The source game files are never uploaded anywhere by this builder.

One system prerequisite may be required:
  Visual Studio 2022 Build Tools + Windows SDK (Desktop C++ workload)

If missing, the builder stops BEFORE downloading the large LLVM archive and
asks you to run INSTALL_MS_BUILD_TOOLS.cmd. Nothing installs silently.

Output:
  out\portable\Dantes_Inferno_RUN00\

Launch with:
  out\portable\Dantes_Inferno_RUN00\LAUNCH_RUN00.cmd
