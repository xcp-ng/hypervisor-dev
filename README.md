<!-- markdown-toc start - Don't edit this section. Run M-x markdown-toc-refresh-toc -->
**Table of Contents**

- [Introduction](#introduction)
  - [Pre-requisites](#pre-requisites)
    - [Get a working build environment](#get-a-working-build-environment)
- [Adding a new binary kernel module](#adding-a-new-binary-kernel-module)
  - [Pull and get all sub-modules](#pull-and-get-all-sub-modules)
  - [Add the new RPM repo as sub-module](#add-the-new-rpm-repo-as-sub-module)
  - [Refreshing the kabi.locked_list file](#refreshing-the-kabilocked_list-file)
- [Upgrading kernel to latest upstream](#upgrading-kernel-to-latest-upstream)
  - [Pre-requisites](#pre-requisites-1)
    - [Git repositories](#git-repositories)
    - [Dev tooling](#dev-tooling)
  - [Rebase the kernel to latest upstream](#rebase-the-kernel-to-latest-upstream)
    - [Check if the patch being applied was not already in your new onto branch:](#check-if-the-patch-being-applied-was-not-already-in-your-new-onto-branch)
      - [If yes](#if-yes)
      - [If no](#if-no)
    - [Create a branch from the rebased HEAD](#create-a-branch-from-the-rebased-head)
    - [Build Kernel RPMs](#build-kernel-rpms)
      - [Update the origin tarball](#update-the-origin-tarball)
        - [Download](#download)
        - [Verify the signature of your tarball:](#verify-the-signature-of-your-tarball)
        - [Commit](#commit)
      - [Build the kernel RPMs](#build-the-kernel-rpms)
        - [Builds failures](#builds-failures)
          - [Incorrect conflict resolution](#incorrect-conflict-resolution)
          - [Kernel .config check fails](#kernel-config-check-fails)
          - [kABI breaking changes](#kabi-breaking-changes)
    - [Verify source RPM generate the same sources](#verify-source-rpm-generate-the-same-sources)
  - [Review your rebase](#review-your-rebase)
    - [Dropped commits on the rebase have a reason](#dropped-commits-on-the-rebase-have-a-reason)
    - [Patch-ids changes have a reason documented](#patch-ids-changes-have-a-reason-documented)
    - [Special care for added commits](#special-care-for-added-commits)
  - [Look for kABI breakage](#look-for-kabi-breakage)
    - [Build kernel RPMs from before the rebase](#build-kernel-rpms-from-before-the-rebase)
    - [Repeat process for the rebased kernel](#repeat-process-for-the-rebased-kernel)
    - [Check if symbols we care about have been modified](#check-if-symbols-we-care-about-have-been-modified)
  - [[WiP] How to fix kABI breakage](#wip-how-to-fix-kabi-breakage)
    - [Identify breaking commit](#identify-breaking-commit)
    - [Unknown to full definition](#unknown-to-full-definition)
    - [Struct fields changes](#struct-fields-changes)
    - [Function prototype changes](#function-prototype-changes)
  - [Finalizing](#finalizing)

<!-- markdown-toc end -->


# Introduction

Read [README.kabi.txt](scripts/README.kabi.txt) to get an introduction on
Genksyms and kernel ABI.

This high-level diagram shows the different files involved in the process:

![kABI files](imgs/kabi_diagram.png "kABI files")

> [!NOTE]
>
> The workflows described here are still very manual.  In the future, many
> of those manual steps will be automated so that the time is spent on
> fixing problems as opposed to finding+fixing them.

## Pre-requisites

### Get a working build environment

```bash
git clone git@github.com:xcp-ng/xcp-ng-build-env.git
cd xcp-ng-build-env

# Build the docker image
./container/build.sh 8.3

# Install the xcp-ng-dev CLI through
pip install -e ./
```

# Adding a new binary kernel module

## Pull and get all sub-modules

Let's make sure we work on top of master and that we have all the drivers
sub-modules properly initialized as a pre-requisite step.

```bash
git pull --rebase origin master
git submodule --init
```

## Add the new RPM repo as sub-module

```bash
git submodule add <driver_name> <driver_repo>
git commit -s -m "<driver_name>: add to the list of submodules."
```

## Refreshing the kabi.locked_list file

As a new driver is added, we need to make sure we do not break the kABI it
relies in future kernel updates.  This will rebuild locally all the drivers
so that we can extract all the exported symbols they reference.

```bash

# Refresh the list of locked symbols
./scripts/generate_locked_list.sh ./kernel-abis/xcpng-8.3-kabi_lockedlist
git add ./kernel-abis/xcpng-8.3-kabi_lockedlist

# Refresh the types of information of locked symbols
./scripts/kabi consolidate --kabi ./kernel-abis/xcpng-8.3-kabi_lockedlist --input ./kernel-abis/Symtypes.build-4.19.19 --output ./kernel-abis/Modules.kabi-4.19.19
git add kernel-abis/Modules.kabi-4.19.19

git commit -s -m "kernel-abis: refreshed the list of locked symbols due to <driver_name> addition."
```

# Upgrading kernel to latest upstream

## Pre-requisites

### Git repositories

You will need two different repositories, one containing the source code,
and one containing the src RPM content that we will update as we are
rebasing the source code branches:

- [linux source repository](https://github.com/xcp-ng/linux)
- [source RPM repository](https://github.com/xcp-ng-rpms/kernel)

### Dev tooling

We'll need two different tools present in a separate repository,
`git-review-rebase` and `git-import-srpm`, let's make sure we have both
available:

```bash
git clone git@github.com:xcp-ng/git-review-rebase.git
cd git-review-rebase
pip install -e ./
```

Note that `git-import-srpm` is a simple bash script and doesn't need any
prior configuration before use, it is present in `scripts/git-import-srpm`.

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
## -162,6 +162,6 @@  Patch75: 0002-gfs2-clean_journal-improperly-set-sd_log_flush_head.patch
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
git checkout -B <your-name>-rebase-to-4.19.325
```

### Build Kernel RPMs

Make sure all changes to the `SPECS/kernel.spec` file are committed and
that any modified patches are also added at this point (`git status -u`
ftw).

#### Update the origin tarball

##### Download

Because the starting point of the patch-queue is different, you'll need to
download a tarball matching the onto point you've used, as well as its
signature file:

- [linux-4.19.325.tar.gz](https://cdn.kernel.org/pub/linux/kernel/v4.x/linux-4.19.325.tar.gz)
- [linux-4.19.325.tar.sign](https://cdn.kernel.org/pub/linux/kernel/v4.x/linux-4.19.325.tar.sign)

##### Verify the signature of your tarball:

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

##### Commit

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
 Source1: kernel-x86_64.
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

#### Build the kernel RPMs

```bash
cd /path/to/rpm/repo
xcp-ng-dev container build 8.3 ./
```

##### Builds failures


###### Incorrect conflict resolution

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

###### Kernel .config check fails

A source of errors when building the RPM is when the defconfig has changed,
to update it you can use `--no-exit` to your `xcp-ng-dev container build`
command line to be dropped inside the container and then, in another
terminal find the container id and copy the config file from it:

```bash
# Get the docker id
docker ps

# Copy the .config
docker cp <container_id>:/home/builder/rpmbuild/BUILD/linux-4.19.325/.config /path/to/rpm/repo/SOURCES/kernel-x86-64.config

```

Audit the changes to the `.config` file, and create a separate commit for
it.  This will need to be carefully reviewed as to make sure we're not
adding or removing any important kernel config.  You can then try again to
build the RPM.


###### kABI breaking changes

Once the kernel is built, the `check-kabi` script will compare the
`Modules.symvers` file with the `Module.kabi` file included in the source
and will fail if any symbols were changed.  You can ignore this problem for
now and consider the build as succeeding as the `check-kabi` runs late in
the process.  You can follow the rest of the chapter, and handle kABI
breakage later in [Look for kABI breakage](#look-for-kabi-breakage).

### Verify source RPM generate the same sources

Once your rebase is done and your RPM builds just fine, it is important to
verify that your src RPM will generate the same sources.

```bash
cd /path/to/rpm/repo
git commit -s -m "kernel: rebase to v4.19.325"
~/path/to/xcp/repo/scripts/git-import-srpm HEAD
```

This should create a new branch, you can then use `git diff
<your_name>-rebase-4.19.325 <newly_imported_branch>` to make sure there are
zero diffs.

## Review your rebase

You should have installed `git-review-rebase` from the pre-requisites
steps, now is time to use it.

Go check its [README](https://github.com/xcp-ng/git-review-rebase) for more information.

### Dropped commits on the rebase have a reason

There maybe commits that were present on the previous branch that simply do
not apply on top of the new onto point.  These are not to be confused with
commits that were present in the initial rebased range and that were
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
was a conflict (i.e. pointing to the commit in the new onto that lead to
the conflict) MUST be present in the commit description to facilitate
reviews and document the problems.

The reviewer will be able to "replay" the rebase of the particular commit
using `git-rebase-review` to compare their resolution with yours.

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
> either deemed buggy or was superceded by a commit fixing differently
> (hopefully in a better way) the same issue.

## Handling kABI breakage

At this point the kernel RPMs built just fine but we don't know how much of
the kABI has changed.  Our current policy with regards to kABI changes is
that it MUST not change any kABI required by binary modules we are shipping
(otherwise, said modules need to be rebuilt, and a new install ISO
generated).

In order to know what's changed, we'll need two builds of the kernel RPMs,
one before the rebase, and one after, with `KBUILD_SYMTYPES=y`, so that
metadata about types are saved and we can use them to infer which commits
introduced the kABI changes.  To learn more about this, you can read the
[README.kabi.txt](./scripts/README.kabi.txt) file.

### Build kernel RPMs from before the rebase

> [!NOTE]
>
> The Symtypes file for the currently released kernel should already be
> present in the `kernel-abis/` directory so this step might be skippable.
> OTOH, doing it is not that long and allows you to have a `vmlinux.o` from
> the currently released kernel which will be useful along with `pahole` to
> correct kABI changes.

Add `export KBUILD_SYMTYPES=y` before the `make` command in the `%build`
step, then build:

```bash
cd /path/to/rpm/repo/

git checkout origin/master
sed -i 's/^%build$/%build\nexport KBUILD_SYMTYPES=y\n/' SPECS/kernel.spec
xcp-ng-dev container build 8.3 ./
```

Collect all the types information with:

```bash
./scripts/kabi collect /path/to/rpm/repo/BUILD/kernel-4.19.19 --output ./kernel-abis/Symtypes.build-v4.19.19

```

Save the build directory for later (it contains vmlinux.o which we will
need to get dwarf information on types):

```bash
cp -r /path/to/rpm/repo/BUILD/kernel-4.19.19 /tmp/
```

### Repeat process for the rebased kernel

```bash
cd /path/to/rpm/repo/

git checkout rebased_branch
sed -i 's/^%build$/%build\nexport KBUILD_SYMTYPES=y\n/' SPECS/kernel.spec
xcp-ng-dev container build 8.3 ./
```

Collect all the types information:

```bash
./scripts/kabi collect /path/to/rpm/repo/BUILD/linux-4.19.325 --output ./kernel-abis/Symtypes.build-v4.19.325
```

Minimize the Symtypes file to only include symbols that are used by binary
drivers we are shipping.

```bash
./scripts/kabi consolidate --kabi ./kernel-abis/xcpng-8.3-kabi_lockedlist --input ./kernel-abis/Symtypes.build-4.19.325 --output ./kernel-abis/Modules.kabi-4.19.325
```

Save the build directory for later use with `pahole`:

```bash
cp -r /path/to/rpm/repo/BUILD/linux-4.19.325 /tmp/
```


### Check if symbols we care about have been modified

```bash
./scripts/kabi compare --no-print-symbol ./kernel-abis/Modules.kabi-4.19.19 ./kernel-abis/Modules.kabi-4.19.325
```

If nothing shows up, no kABI breakage and you can open a PR with your
changes and follow the usual release process.  If there were kABI breakage,
follow chapter "Fixing kABI breakage" before opening your PR.

Typical output will look like this:

```diff
--- struct netns_ipv4 - Baseline
+++ struct netns_ipv4 - Comparison
@@ -52,6 +52,7 @@
        int sysctl_tcp_l3mdev_accept;
        int sysctl_tcp_mtu_probing;
        int sysctl_tcp_base_mss;
+       int sysctl_tcp_min_snd_mss;
        int sysctl_tcp_probe_threshold;
        u32 sysctl_tcp_probe_interval;
        int sysctl_tcp_keepalive_time;
@@ -128,4 +129,5 @@
        struct fib_notifier_ops *ipmr_notifier_ops;
        unsigned int ipmr_seq;
        atomic_t rt_genid;
+       siphash_key_t ip_id_key;
 }

--- struct cxgbi_sock - Baseline
+++ struct cxgbi_sock - Comparison
@@ -40,6 +40,7 @@
        struct sk_buff_head receive_queue;
        struct sk_buff_head write_queue;
        struct timer_list retry_timer;
+       struct completion cmpl;
        int err;
        rwlock_t callback_lock;
        void *user_data;
```

Each change will require either a kABI fix, if possible, or reverting the
patch that introduced the change.

## [WiP] How to fix kABI breakage

### Manually Identifiyng breaking commit

The fastest way is to first identify where the symbol definition is coming
from, e.g. for `struct cxgbi_sock` above, we'd:

```bash
$ git grep -l 'struct cxgbi_sock {'
drivers/scsi/cxgbi/libcxgbi.h
```

Then use git log pickaxe to find which commit added or removed the field:

```bash
$ git log --oneline -G 'completion cmpl;'  --right-only ${prev_branch}..HEAD -- drivers/scsi/cxgbi/libcxgbi.h
4c3b23e90307 scsi: cxgb4i: add wait_for_completion()
```

The easiest way is obviously to revert the infringuing commit, but some
tricks might be possible to avoid this last resort measures, check next
chapters to see if it's possible depending on the change.

### Using `kabi tui`

![kabi tui demo](imgs/demo.gif "kabi tui demo")

#### Unknown to full definition
#### Struct fields changes
#### Function prototype changes

## Finalizing

Rebuild one more time the RPM with all your kABI fixes and re-import it as
a branch with `git-import-srpm`, make sure you have no diff with the branch
you were working on in the source repo.  If all is good, you can push your
src rpm repo branch, and trigger a scratch build:

```bash
koji_build.py --scratch v8.3-incoming .
```

Monitor for build errors as usual, and if all is good, time for testing
your build and making sure all our drivers can be modprobed without the
kernel module loader complaining about symbol versions mismatches.
