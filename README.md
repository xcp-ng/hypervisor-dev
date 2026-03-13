<!-- markdown-toc start - Don't edit this section. Run M-x markdown-toc-refresh-toc -->
**Table of Contents**

- [Introduction](#introduction)
  - [Branch convention](#branch-convention)
- [Pre-requisites](#pre-requisites)
  - [Get a working build environment](#get-a-working-build-environment)
  - [Install the git-review-rebase tool](#install-the-git-review-rebase-tool)
- [Adding a new binary kernel module](#adding-a-new-binary-kernel-module)
  - [Pull and get all sub-modules](#pull-and-get-all-sub-modules)
  - [Add the new RPM repo as sub-module](#add-the-new-rpm-repo-as-sub-module)
  - [Refreshing the kabi.locked_list file](#refreshing-the-kabilocked_list-file)
- [Upgrading kernel to latest upstream](#upgrading-kernel-to-latest-upstream)
  - [Pre-requisites git repositories](#pre-requisites-git-repositories)
  - [Pre-requisites dev tooling](#pre-requisites-dev-tooling)
  - [Rebase the kernel to latest upstream](#rebase-the-kernel-to-latest-upstream)
    - [Check if the patch being applied was not already in your new onto branch:](#check-if-the-patch-being-applied-was-not-already-in-your-new-onto-branch)
      - [If yes](#if-yes)
      - [If no](#if-no)
    - [Create a branch from the rebased HEAD](#create-a-branch-from-the-rebased-head)
  - [Update the origin tarball](#update-the-origin-tarball)
    - [Download](#download)
    - [Verify the signature of your tarball](#verify-the-signature-of-your-tarball)
    - [Commit](#commit)
  - [Build the kernel RPMs](#build-the-kernel-rpms)
    - [Builds failures](#builds-failures)
      - [Incorrect conflict resolution](#incorrect-conflict-resolution)
      - [Kernel .config check fails](#kernel-config-check-fails)
      - [kABI breaking changes](#kabi-breaking-changes)
  - [Verify source RPM generates the same sources](#verify-source-rpm-generates-the-same-sources)
  - [Review your rebase](#review-your-rebase)
    - [Dropped commits on the rebase have a reason](#dropped-commits-on-the-rebase-have-a-reason)
    - [Patch-ids changes have a reason documented](#patch-ids-changes-have-a-reason-documented)
    - [Special care for added commits](#special-care-for-added-commits)
- [Adding an upstream patch to our patch-queue](#adding-an-upstream-patch-to-our-patch-queue)
  - [Cherry-pick the commit](#cherry-pick-the-commit)
  - [Update the RPM repo](#update-the-rpm-repo)
  - [Build the kernel RPMs](#build-the-kernel-rpms-1)
  - [Verify source RPM generates the same sources](#verify-source-rpm-generates-the-same-sources-1)
- [Incorporating XenServer patch-queue changes](#incorporating-xenserver-patch-queue-changes)
  - [Merging changes back in](#merging-changes-back-in)
  - [Build and verify](#build-and-verify)

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
## Install the git-review-rebase tool

The script lives in this repository, to install:

```bash
cd scripts/git-review-rebase
pip install -e .
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

# Upgrading kernel to latest upstream

## Pre-requisites git repositories

You will need two different repositories, one containing the source code,
and one containing the src RPM content that we will update as we are
rebasing the source code branches:

- [linux source repository](https://github.com/xcp-ng/linux)
- [source RPM repository](https://github.com/xcp-ng-rpms/kernel)

## Pre-requisites dev tooling

You should have installed `git-review-rebase` from the [Install the
git-review-rebase tool chapter](#install-the-git-review-rebase-tool), we'll
also need `git-import-srpm` which is present in the [main
xcp](https://www.github.com/xcp-ng/xcp) repository:

```bash
git clone git@github.com:xcp-ng/xcp.git
# Lives in scripts/git-import-srpm
```

Note that `git-import-srpm` is a simple bash script and doesn't need any
prior configuration before use, it is present in
`/path/to/xcp/repo/scripts/git-import-srpm`.

## Rebase the kernel to latest upstream

Find the last branch that was released,
e.g. `kernel/xcpng-4.19.19-8.0.44.1/base`, we'll use it as the source of
the rebased commits:

```bash
cd /path/to/source/repo

# Last released branch
prev_branch=$(git branch -r --list origin/kernel/xcpng\*/base | sort -V | tail -n 1)

# Extra ^0 suffix to reference the commit and make sure original branch isn't updated
git rebase ${prev_branch%/base}/pre-base ${prev_branch}^0 --onto v4.19.325
```

> [!NOTE]
>
> Replace `v4.19.325` with the upstream tag you are rebasing onto

As you are rebasing, you will get conflicts.  For each conflict:

### Check if the patch being applied was not already in your new onto branch:

An easy way to check this is to use the title of the failing patch:

```bash
git log --oneline --right-only --grep "<title_goes_here>" ${prev_branch}...HEAD
```

#### If yes

Drop the patch `git rebase --skip` and comment the patch from the list of
patches in the `SPECS/kernel.spec` file, referencing the upstream sha1 of
the commit, e.g.:

```diff
diff --git a/SPECS/kernel.spec b/SPECS/kernel.spec
index 181b3a467d87..5997a384f4ef 100644
--- a/SPECS/kernel.spec
+++ b/SPECS/kernel.spec
@@ -79,23 +79,23 @@ Provides: kernel-%{_arch} = %{version}-%{release}

 Source0: kernel-4.19.19.tar.gz
 Source1: kernel-x86_64.config
 Source2: macros.kernel
-Patch0: 0001-Fix-net-ipv4-do-not-handle-duplicate-fragments-as-ov.patch
-Patch1: 0001-xen-privcmd-allow-fetching-resource-sizes.patch
-Patch2: 0001-block-genhd-add-groups-argument-to-device_add_disk.patch
-Patch3: 0002-nvme-register-ns_id-attributes-as-default-sysfs-grou.patch
-Patch4: 0001-mm-zero-remaining-unavailable-struct-pages.patch
-Patch5: 0002-mm-return-zero_resv_unavail-optimization.patch
-Patch6: 0001-mm-page_alloc.c-fix-uninitialized-memmaps-on-a-parti.patch
+# Patch0: 0001-Fix-net-ipv4-do-not-handle-duplicate-fragments-as-ov.patch: c763a3cf502 Fix "net: ipv4: do not handle duplicate fragments as overlapping"
+# Patch1: 0001-xen-privcmd-allow-fetching-resource-sizes.patch: d8099663adc9 xen/privcmd: allow fetching resource sizes
+# Patch2: 0001-block-genhd-add-groups-argument-to-device_add_disk.patch: 1bf6a186c452 block: genhd: add 'groups' argument to device_add_disk
+# Patch3: 0002-nvme-register-ns_id-attributes-as-default-sysfs-grou.patch: ea7ac82cf4d8 nvme: register ns_id attributes as default sysfs groups
+# Patch4: 0001-mm-zero-remaining-unavailable-struct-pages.patch: 9ac5917a1d28 mm: zero remaining unavailable struct pages
+# Patch5: 0002-mm-return-zero_resv_unavail-optimization.patch: f19a50c1e3ba mm: return zero_resv_unavail optimization
+# Patch6: 0001-mm-page_alloc.c-fix-uninitialized-memmaps-on-a-parti.patch: 0a69047d8235 mm/page_alloc.c: fix uninitialized memmaps on a partially populated last section
```

#### If no

Manually resolve the conflicts and make sure to add a comment in the commit
description to explain the reason of the conflict, as well as a reference
to the commit that introduced the conflict `git add -u; git commit` e.g:

```text
[Quentin: rebase from v4.19.19 to v4.19.325 conflicts:
 - path/to/file/with/conflict.c: <sha1> ("<commit title>") changed the context
   by <doing something>.]
```

Once the conflict is resolved and committed, generate a new patch with `git
format-patch -1` and copy it to the `SOURCES/` directory in the rpm repo,
add a suffix to the patch file referencing the new onto point, e.g.:

```bash
cp 0001-xen-blkback-fix.patch /path/to/rpm/repo/SOURCES/0001-xen-blkback-fix-rebase-to-v4.19.325.patch
                                                                             ^^^^^^^^^^^^^^^^^^^
```

Then update the `PatchXXXX 0001-xen-blkback-fix.patch` line in the
`SPECS/kernel.spec` file, e.g.:

```diff
diff --git a/SPECS/kernel.spec b/SPECS/kernel.spec
index 181b3a467d87..5997a384f4ef 100644
--- a/SPECS/kernel.spec
+++ b/SPECS/kernel.spec
@@ -162,6 +162,6 @@  Patch75: 0002-gfs2-clean_journal-improperly-set-sd_log_flush_head.patch
 Patch76: 0001-gfs2-Replace-gl_revokes-with-a-GLF-flag.patch
 Patch77: 0005-gfs2-Remove-misleading-comments-in-gfs2_evict_inode.patch
-Patch78: 0006-gfs2-Rename-sd_log_le_-revoke-ordered.patch
+Patch78: 0001-gfs2-Rename-sd_log_le_-revoke-ordered-rebase-325.patch
 Patch79: 0007-gfs2-Rename-gfs2_trans_-add_unrevoke-remove_revoke.patch
 Patch80: 0001-iomap-Clean-up-__generic_write_end-calling.patch
```

And carry on your rebase with `git rebase --cont`.

### Create a branch from the rebased HEAD

Once your initial rebase is done, create a branch from your HEAD commit:

```bash
cd /path/to/source/repo
git checkout -B <your-name>-rebase-to-<upstream_tag>
```

## Update the origin tarball

### Download

Because the starting point of the patch-queue is different, you'll need to
download a tarball matching the onto point you've used, as well as its
signature file, e.g.:

- [linux-4.19.325.tar.gz](https://cdn.kernel.org/pub/linux/kernel/v4.x/linux-4.19.325.tar.gz)
- [linux-4.19.325.tar.sign](https://cdn.kernel.org/pub/linux/kernel/v4.x/linux-4.19.325.tar.sign)

### Verify the signature of your tarball

```bash
gunzip --keep linux-4.19.325.tar.gz
gpg --verify linux-4.19.325.tar.sign linux-4.19.325.tar
```

You might need to import Linus' and Greg KH's keys first:

```bash
gpg --locate-keys torvalds@kernel.org gregkh@kernel.org
```

Double check the key signatures you've imported with [kernel.org
signatures](https://www.kernel.org/category/signatures.html)

For Ulrich Hecht, you can find his public key through the [Linux foundation
CIP
Wiki](https://wiki.linuxfoundation.org/civilinfrastructureplatform/cipkernelmaintenance),
current link as of February 2026 is
[here](https://git.kernel.org/pub/scm/docs/kernel/pgpkeys.git/plain/keys/36A3BADB36B27332.asc).

You can download it locally and then import it into your `gpg` keyring:

```bash
gpg --import < ~/Downloads/36A3BADB36B27332.asc
```

### Commit

Once everything is verified, you can add the unmodified tarball into the
SOURCES directory and update the `Source0` line of the `SPECS/kernel.spec`
file to point to it.  Also change the `usrver`, `package_srccommit` and
`Version` variable, e.g.:

```diff
diff --git a/SPECS/kernel.spec b/SPECS/kernel.spec
index 181b3a467d87..5997a384f4ef 100644
--- a/SPECS/kernel.spec
+++ b/SPECS/kernel.spec
@@ -1,8 +1,8 @@
 %global package_speccommit ccb8ee3c01ade60b0ee7a22436d4b25d84702ae4
-%global usver 4.19.19
+%global usver 4.19.325
 %global xsver 8.0.44
 %global xsrel %{xsver}%{?xscount}%{?xshash}
-%global package_srccommit refs/tags/v4.19.19
+%global package_srccommit refs/tags/v4.19.325
 %define uname 4.19.0+1
 %define short_uname 4.19
 %define srcpath /usr/src/kernels/%{uname}-%{_arch}
@@ -36,7 +36,7 @@

 Name: kernel
 License: GPLv2
-Version: 4.19.19
+Version: 4.19.325
 Release: %{?xsrel}.1%{?dist}
 ExclusiveArch: x86_64
@@ -79,23 +79,23 @@ Provides: kernel-%{_arch} = %{version}-%{release}
 Requires(post): coreutils kmod
 Requires(posttrans): coreutils dracut kmod

-Source0: kernel-4.19.19.tar.gz
+Source0: linux-4.19.325.tar.gz
 Source1: kernel-x86_64.config
 ```

Commit as usual the resulting changes.

> [!Note]
>
> XenServer orig tarballs are somewhat slightly modified from the ones on
> kernel.org, and will untar inside `kernel-<Version>` whereas tarballs
> from kernel.org will untar inside `linux-<Version>`.  You can specify the
> format on the `%autosetup` line from the `%prep` step, using the `-n`
> option, e.g.:
>
> ```diff
> diff --git a/SPECS/kernel.spec b/SPECS/kernel.spec
> index 5997a384f4ef..1778746e2c86 100644
> --- a/SPECS/kernel.spec
> +++ b/SPECS/kernel.spec
> @@ -787,7 +787,7 @@ Provides: python2-perf
>  %{pythonperfdesc}
>
>  %prep
> -%autosetup -p1
> +%autosetup -p1 -n linux-%{version}
>  %{?_cov_prepare}
>
>  %build
> ```

## Build the kernel RPMs

We should be ready to start building at this point:

```bash
cd /path/to/rpm/repo
xcp-ng-dev container build 8.3 ./
```

### Builds failures


#### Incorrect conflict resolution

Go back to the source repository, find the commit that introduced the build
failure, and rework it, e.g.:

```bash

# Use git log pickaxes to find incriminating commit
git log --oneline -G<line_content> <prev_branch>..<new_branch> -- path/to/file/with/compiler/error.c

# Modify the commit
git rebase -i <bad_commit>^
# Mark the first commit as edit, save the git rebase TODO

# Fix the code and continue the rebase, make sure to add a comment to the
# commit description explaining why you had to make the change
git add -u
git commit --amend

# Generate a new patch
git format-patch -1

# Continue the rebase
git rebase --cont
```

Copy the new patches to the `SOURCES` directory in your RPM repo like when
you [resolved conflict](#if-no) and update the `SPECS/kernel.spec`
accordingly.  `git add` the new patches as well as your `SPECS/kernel.spec`
changes, and re-run a build.  Repeat until it succeeds.

> [!NOTE]
>
> You can get faster build/change/test iterations by adding `--no-exit` to
> the `xcp-ng-dev container build` CLI and copy/pasting the `make` command
> line that is used to build the kernel so that you benefit from iterative
> builds.  If you do that, you'll still need a final run xcp-ng-dev
> container build to make sure everything is good to go from scratch.

#### Kernel .config check fails

A source of errors when building the RPM is when the defconfig has changed,
to update it you can use `--no-exit` to your `xcp-ng-dev container build`
command line to be dropped inside the container and then, in another
terminal find the container id and copy the config file from it:

```bash
# Get the docker id
docker ps

# Copy the .config
docker cp <container_id>:/home/builder/rpmbuild/BUILD/linux-4.19.325/.config /path/to/rpm/repo/SOURCES/kernel-x86_64.config

```

Audit the changes to the `.config` file, and create a separate commit for
it.  This will need to be carefully reviewed as to make sure we're not
adding or removing any important kernel config.  You can then try again to
build the RPM.


#### kABI breaking changes

Once the kernel is built, the `check-kabi` script will compare the
`Modules.symvers` file with the `Module.kabi` file included in the source
and will fail if any symbols were changed.

[TODO: write chapter on handling kABI changes]

## Verify source RPM generates the same sources

Once your rebase is done and your RPM builds just fine, it is important to
verify that your src RPM will generate the same sources.

```bash
cd /path/to/rpm/repo
git commit -s -m "kernel: rebase to v4.19.325"
/path/to/xcp/repo/scripts/git-import-srpm HEAD
```

This should create a new branch, you can then use `git diff
<your_name>-rebase-4.19.325 <newly_imported_branch>` to make sure there are
zero diffs.

## Review your rebase

You should have installed `git-review-rebase` from the pre-requisites
steps, now is time to use it.

![git-review-rebase main view](imgs/git-review-rebase-main.png "git-review-rebase main view")

You can press `enter` when in the main view to see a side-by-side diff of commits:

![git-review-rebase diff view](imgs/git-review-rebase-diff.png "git-review-rebase diff view")

You can toggle the blame output when in the diff view by pressing `b`,
allows to see which commit introduced the conflict:

![git-review-rebase diff blame view](imgs/git-review-rebase-diff-blame.png "git-review-rebase diff blame view")

Go check its [README](https://github.com/xcp-ng/git-review-rebase) for more information.

### Dropped commits on the rebase have a reason

There may be commits that were present on the previous branch that simply
do not apply on top of the new onto point.  These are not to be confused
with commits that were present in the initial rebased range and that were
dropped during the rebase because an equivalent commit was present as
ancestor of the new onto point, as those should not show as dropped in the
`git-review-rebase` TUI, instead they'll show as matched to their
equivalent upstream commit.

Dropped commits need to have a comment added to them through the
`git-review-rebase` TUI (which is using `git notes` internally to save/show
them) explaining why a commit disappeared from the rebase, e.g.:

```text
commit ab8c1257dd2213bbf9b0ef603bc50398d6bd0e80
Author: Thierry Escande <thierry.escande@vates.tech>
Date:   Wed Jun 12 14:47:11 2024 +0200

    Backport tg3 driver code from kernel v4.19.315

Notes:
    Quentin: Latest tg3 driver included in v4.19.325 rebase.
```

Here there were no single commit to be matched in the new branch because
the commit from the previous branch was a massive squash, as such it
appears as "dropped", and the reason is documented.

### Patch-ids changes have a reason documented

Most patch-id changes imply there was a conflict during the rebase - as
such, a clear explanation as to what was the conflict as well _why_ there
was a conflict (i.e. pointing to the commit in the new onto that led to
the conflict) MUST be present in the commit description to facilitate
reviews and document the problems.

The reviewer will be able to "replay" the rebase of the particular commit
using `git-review-rebase` to compare their resolution with yours.

Don't hesitate to use the blame output in the `git-review-rebase` command
to find upstream commits causing the conflicts.

### Special care for added commits

> [!WARNING]
>
> Seeing an added commit at this point of the process should not happen -
> if it does it is very likely pointing to a commit that was applied AND
> reverted (or partially reverted) on the new onto point, allowing it to be
> applied again.  Reverts are here for a reason, so this needs
> investigation and likely dropping the commit on the rebase because it was
> either deemed buggy or was superseded by a commit fixing differently
> (hopefully in a better way) the same issue.

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

# Incorporating XenServer patch-queue changes

Our `SPECS/kernel.spec` contains two blocks of patches: XenServer's
(numbered `Patch0` onwards) followed by ours (numbered `Patch1000`
onwards).  When XenServer releases a new kernel SRPM, their patch-queue
changes and we need to incorporate those changes into our branch.

The following assumes the new XenServer SRPM is already imported as the
`XS-8.3` branch in the SRPM repo.

## Merging changes back in

```bash
cd /path/to/source/rpm/repo
git merge origin/master
```

If you're lucky, XenServer folks added new patches on top of their current
patch-queue, such that the numbering for all the existing patches remain
unchanged.  In this case, the merge should be pretty straightforwards and
without much difficult conflicts.

OTOH, if they've added new patches in the middle of the workqueue, that's
where things get a little trickier as you will get pretty disgusting
conflicts.  Resolve all conflicts that are _not_ related to the Patch
lines, then discard any conflicts in those Patch lines (keep as they were
before the cherry-pick), then manually copy/paste the extra `Patch` lines.
You can use the following one-liner to get the list of added `Patch` lines
like:

``` bash
cd /path/to/source/rpm/repo/
git diff origin/XS-8.3^- --word-diff --word-diff-regex='[^[:space:]]|Patch[0-9]+:' -- SPECS \
	| grep '^{+Patch.*+}$' \
	| sed -e 's/+}$//' -e 's/^{//'
```

All the Patch indexes can now be "offset" with the
[change_spec_patch_indexes.sh](./scripts/change_spec_patch_indexes.sh)
script, for example, if the above `git diff` command gives you:

``` diff
+Patch444: 0002-SUNRPC-Remove-the-bh-safe-lock-requirement-on-xprt-t.patch
+Patch445: 0003-SUNRPC-Replace-direct-task-wakeups-from-softirq-cont.patch
+Patch446: 0004-SUNRPC-Replace-the-queue-timer-with-a-delayed-work-f.patch
+Patch447: 0001-nbd-fix-possible-sysfs-duplicate-warning.patch
+Patch448: 0001-nbd-protect-cmd-status-with-cmd-lock.patch
+Patch449: 0001-nbd-handle-racing-with-error-ed-out-commands.patch
+Patch450: 0001-nbd-fix-a-block_device-refcount-leak-in-nbd_release.patch
+Patch451: 0001-nbd-Aovid-double-completion-of-a-request.patch
+Patch452: 0001-nbd-don-t-handle-response-without-a-corresponding-re.patch
+Patch453: 0001-nbd-make-sure-request-completion-won-t-concurrent.patch
```

That's **10** extra patches, starting at `Patch444`, so you'd run:

``` bash
./scripts/change_spec_patch_indexes.sh /path/to/source/rpm/repo/SPECS/kernel.spec 444 10
```

The script should be smart enough to fix all indexes for you as well as
ignore patch indexes that are specific to XCP-ng.

You can then git add and git commit.

## Build and verify

Once all changes are incorporated, build the RPMs:

```bash
cd /path/to/srpm/repo
xcp-ng-dev container build 8.3 ./
```

If the build fails, refer to [Incorrect conflict
resolution](#incorrect-conflict-resolution).

Once built, `check-kabi` will verify the symbol exports and it should not
fail at this step given XenServer folks guarantee a stable kABI.

Finally, verify that the source RPM can be imported as a source branch
cleanly using the `git-import-srpm` script:

```bash
git commit -s -m "kernel: incorporate XS <xs-version> changes"
/path/to/xcp/repo/scripts/git-import-srpm HEAD
```
