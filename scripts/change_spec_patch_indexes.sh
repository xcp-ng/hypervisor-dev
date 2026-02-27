#! /bin/bash -eu
#
# This script can be used to add/remove a specific offset from all PatchXXX
# directive in a spec file, which can help when merging back changes from
# XenServers where they add new patches in the middle of their patch-queue.
#
# For example if they've added 5 patches starting at patch index 100, then
# the previous Patch100 is now Patch105, Patch101 is now Patch106, etc.
# This script takes care of the rewriting, give it a spec file, an index to
# start and an offset.
#
# Usage: ./change_spec_patch_indexes.sh spec_file start_index offset

function usage() {
    echo Usage: "$0" SPEC_FILE START_INDEX OFFSET
}

if [[ $# -ne 3 ]]; then
    usage
    exit 1
fi

spec_file="$1"
start_index="$2"
offset="$3"

if [[ ! -e "${spec_file}" ]]; then
    echo "'${spec_file}' does not exist"
    usage
    exit 1
fi

awk -i inplace -v start="$start_index" -v off="$offset" '
  BEGIN {
    xcp_patches = 0
  }
  /^# XCP-ng patches/{
    xcp_patches = 1
  }
  xcp_patches == 0 && /^#?[ ]*Patch[0-9]+/ {
    if (match($0, /^(#[ ]*)?Patch([0-9]+)(.*)/,  patch_line)) {
      comment = patch_line[1]
      patchnum = int(patch_line[2])
      patch = patch_line[3]

      if (patchnum >= start) {
        patchnum = patchnum + off
        printf "%sPatch%d%s\n", comment, patchnum, patch
      } else {
        print
      }
    } else {
      print
    }
    next
  }
  { print }
' "$spec_file"
