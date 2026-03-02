<!-- markdown-toc start - Don't edit this section. Run M-x markdown-toc-refresh-toc -->
**Table of Contents**

- [Introduction](#introduction)
  - [Branch convention](#branch-convention)
- [Pre-requisites](#pre-requisites)
  - [Get a working build environment](#get-a-working-build-environment)
- [Adding a new binary kernel module](#adding-a-new-binary-kernel-module)
  - [Pull and get all sub-modules](#pull-and-get-all-sub-modules)
  - [Add the new RPM repo as sub-module](#add-the-new-rpm-repo-as-sub-module)
  - [Refreshing the kabi.locked_list file](#refreshing-the-kabilocked_list-file)
- [Adding an upstream patch to our patch-queue](#adding-an-upstream-patch-to-our-patch-queue)
  - [Cherry-pick the commit](#cherry-pick-the-commit)
  - [Update the RPM repo](#update-the-rpm-repo)
  - [Build the kernel RPMs](#build-the-kernel-rpms)
  - [Verify source RPM generates the same sources](#verify-source-rpm-generates-the-same-sources)

<!-- markdown-toc end -->

# Introduction

This repository contains information and tools in order to be able to
maintain the XCP-ng Linux kernel and other packages maintained by the
hypervisor & kernel team..  This README will guide you through different
maintenance activities like rebasing our patch-queue onto a new upstream
base, adding a new binary driver to the list of drivers, pulling changes
from the XenServer patch-queue, handling kABI breakage after an update to
the Linux kernel.


## Branch convention

![Branching strategy](imgs/branch_strategy.png "Branching strategy")


We currently use a branch convention in the source code repositories
maintained by the Hypervisor & Kernel team at vates, where for each
released package (qemu, xen, linux), a corresponding source branch is
created in the form:

```
<product>/xcpng-<version>-<release>/base
```

Where product would be `kernel` for the Linux kernel, e.g.: `kernel/xcpng-4.19.325-cip129.8.0.44.1/base`.

For each `/base` branch, a corresponding `/pre-base` branch is created from
the upstream point where the patch-queue of our SRPM was applied onto.  As
such, our patch-queue can be found with the range `/pre-base../base`.

The branches are created by the
[git-import-srpm](https://github.com/xcp-ng/xcp/blob/quentin-git-import-srpm/scripts/git-import-srpm)
script run from within the SRPM repository.

We also have an [elixir instance]() with the source code indexed for all
past released RPMs.

# Pre-requisites

## Get a working build environment

```bash
git clone git@github.com:xcp-ng/xcp-ng-build-env.git
cd xcp-ng-build-env

# Build the docker image
./container/build.sh 8.3

# Install the xcp-ng-dev CLI
uv tool install --editable .
```
# Adding a new binary kernel module

## Pull and get all sub-modules

Let's make sure we work on top of main and that we have all the drivers
sub-modules properly initialized as a pre-requisite step.

```bash
git pull --rebase origin main
git submodule update --init
```

## Add the new RPM repo as sub-module

```bash
git submodule add <driver_repo> drivers/<driver_name>
git commit -s -m "<driver_name>: add to the list of submodules."
```

## Refreshing the kabi.locked_list file

As a new driver is added, we need to make sure we do not break the kABI it
relies in future kernel updates.

In order to do, we maintain a file listing all the symbols our binary
drivers are using from the linux kernel in
`kernel-abis/xcpng-8.3-kabi_lockedlist`.

We need to refresh this file to include symbols from the newly added
driver, the [generate_locked_list.sh](scripts/generate_locked_list.sh)
script does just that:


```bash

# Refresh the list of locked symbols
./scripts/generate_locked_list.sh ./kernel-abis/xcpng-8.3-kabi_lockedlist
git add ./kernel-abis/xcpng-8.3-kabi_lockedlist

# Refresh the types of information of locked symbols
kabi consolidate --kabi ./kernel-abis/xcpng-8.3-kabi_lockedlist --input ./kernel-abis/Symtypes.build-4.19.19 --output ./kernel-abis/Modules.kabi-4.19.19
git add kernel-abis/Modules.kabi-4.19.19

git commit -s -m "kernel-abis: refreshed the list of locked symbols due to <driver_name> addition."
```

# Adding an upstream patch to our patch-queue

Sometimes a fix or improvement from a newer upstream kernel needs to be
backported to our current kernel version.  This chapter describes how to
cherry-pick such a commit and integrate it into our patch-queue.

## Cherry-pick the commit

Find the latest `/base` branch and create a working branch on top of it:

```bash
cd /path/to/source/repo

base_branch=$(git branch -r --list origin/kernel/xcpng\*/base | sort -V | tail -n 1)
git checkout -B <your-name>/add-<short-description> ${base_branch}
```

Cherry-pick the upstream commit (make sure to use -x):

```bash
git cherry-pick -x <upstream-sha1>
```

If the cherry-pick results in conflicts, resolve them and make sure to add
a comment in the commit description explaining the reason for the conflict,
e.g.:

```text
[Quentin: cherry-pick onto v4.19.325 conflicts:
 - path/to/file.c: <sha1> ("<commit title>") changed the context
   by <doing something>.]
```

Generate the patch file once done:

```bash
git format-patch -1
```

## Update the RPM repo

Copy the patch to the `SOURCES/` directory of the RPM repo:

```bash
cp 0001-<patch-name>.patch /path/to/rpm/repo/SOURCES/
```

Add a new `Patch1NNN:` line to `SPECS/kernel.spec`, incrementing the patch
number from the last existing entry within the block for the XCP-ng
patch-queue (which comes after the XenServer patch-queue):

```diff
diff --git a/SPECS/kernel.spec b/SPECS/kernel.spec
index 1778746e2c86..61909253c295 100644
--- a/SPECS/kernel.spec
+++ b/SPECS/kernel.spec
@@ -720,7 +721,7 @@ Source5: prepare-build
 # Patch1000: ceph.patch: already included in v4.19.325
 # Patch1001: tg3-v4.19.315.patch: already included in v4.19.325
 # Patch1002: 0001-perf-probe-Fix-getting-the-kernel-map.patch: 37c6f8089806 perf probe: Fix getting the kernel map
 Patch1003: 0001-ACPI-processor-idle-Check-acpi_bus_get_device-return.patch
 # Patch1004: 0001-scsi-target-Fix-XCOPY-NAA-identifier-lookup.patch: fff1180d24e6 scsi: target: Fix XCOPY NAA identifier lookup
+Patch1005: 0001-<patch-name>.patch
 ```

Commit the result:

```bash
cd /path/to/rpm/repo
git add SOURCES/0001-<patch-name>.patch SPECS/kernel.spec
git commit -s -m "kernel: <short-description>"
```

## Build the kernel RPMs

```bash
xcp-ng-dev container build 8.3 ./
```

If the build fails due to a conflict resolution issue, refer to [Incorrect
conflict resolution](#incorrect-conflict-resolution).

Once the kernel is built, `check-kabi` will compare the exported symbols
against our locked list.

[TODO: write chapter on handling kABI changes]

## Verify source RPM generates the same sources

```bash
/path/to/xcp/repo/scripts/git-import-srpm HEAD
```

Use `git diff <your-branch> <newly_imported_branch>` to verify there are
zero diffs.
