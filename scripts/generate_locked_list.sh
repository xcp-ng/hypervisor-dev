#!/bin/bash -eu

# This script regenerates a locked_list file that contains the list of all
# symbols used by the drivers we ship as binary kernel modules.
#
# Run like this:
#  ./generate_locked_list.sh <OUTPUT_FILE>

OUTPUT_FILE="$1"

VATES_REMOTE="$(git remote -v | grep github.com | grep xcp-ng | awk '{print $1}')"

git fetch ${VATES_REMOTE}

if [[ $(git rev-parse HEAD) -ne $(git rev-parse ${VATES_REMOTE}/master) ]] ; then
    echo "Repository's HEAD is not up-to-date with ${VATES_REMOTE}/master"
    exit 1
fi

if [[ -n $(git status) ]]; then
    echo "Repository has uncommitted changes"
    exit 1
fi

git submodule foreach "
    cd \${path}
    xcp-ng-dev container build 8.3 ./
"

git submodule foreach "
    echo \"[\${name}]\"
    for module in \$(find \${path} -name \\*.ko); do
    	objdump -t \${module} | awk '/UND/{print \"\t\" \$NF}'
    done | sort -u
" > "${OUTPUT_FILE}"
