#! /bin/bash -eu

# Usage: ./patch_offset.sh spec_file start_index offset

spec_file="$1"
start_index="$2"
offset="$3"

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
