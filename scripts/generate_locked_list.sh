#!/bin/bash -eu

# This script regenerates a locked_list file that contains the list of all
# symbols used by the drivers we ship as binary kernel modules.
#
# Run like this:
#  ./generate_locked_list.sh [OPTIONS] <OUTPUT_FILE>
#
# Options:
#   --no-checks          Skip git remote and status checks
#   --skip-driver-build  Skip building drivers in containers

NO_CHECKS=false
SKIP_BUILD=false
OUTPUT_FILE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-checks)
            NO_CHECKS=true
            shift
            ;;
        --skip-driver-build)
            SKIP_BUILD=true
            shift
            ;;
        --append)
            shift
            APPEND_DRIVERS="$1"
            shift
            ;;
        --*)
            echo "Usage: $0 [--no-checks] [--skip-driver-build] <OUTPUT_FILE>"
            exit 1
            ;;
        *)
            OUTPUT_FILE="$1"
            shift
            ;;
    esac
done

if [[ -z "${OUTPUT_FILE}" ]]; then
    echo "Error: OUTPUT_FILE is required"
    echo "Usage: $0 [--no-checks] [--skip-driver-build] <OUTPUT_FILE>"
    exit 1
fi

if [[ "${NO_CHECKS}" == false ]]; then
    VATES_REMOTE="$(git remote -v | grep github.com | grep xcp-ng | grep fetch | awk '{print $1}' | sort -u | head -n 1)"

    git fetch "${VATES_REMOTE}"

    if [[ $(git rev-parse HEAD) != $(git ls-remote "${VATES_REMOTE}" HEAD | cut -f1) ]] ; then
        echo "Repository's HEAD is not up-to-date with ${VATES_REMOTE}/HEAD"
        exit 1
    fi

    if [[ -n $(git status -s) ]]; then
        echo "Repository has uncommitted changes"
        exit 1
    fi
fi

if [[ "${SKIP_BUILD}" == false ]]; then
    #shellcheck disable=SC2016
    if [[ -z "${APPEND_DRIVERS:-}" ]]; then
        git submodule foreach '
            set -eu
            if [ "$(dirname "${sm_path}")" = "drivers/8.3/srpm" ]; then
                xcp-ng-dev container build 8.3 ./
            fi
        '
    else
        for driver_name in ${APPEND_DRIVERS}; do
            (
                cd drivers/8.3/srpm/"${driver_name}"
                xcp-ng-dev container build 8.3 ./
            )
        done
    fi
fi

#shellcheck disable=SC2016
if [[ -z "${APPEND_DRIVERS:-}" ]]; then
    git submodule --quiet foreach '
    set -eu
    if [ "$(dirname "${sm_path}")" != "drivers/8.3/srpm" ]; then
        exit 0
    fi
    echo "[$(basename ${name})]"
    for module in $(find ./ -name \*.ko); do
        objdump -t "${module}" | awk "/UND/{print \"\t\" \$NF}"
    done | sort -u
    ' > "${OUTPUT_FILE}"
else
        for driver_name in ${APPEND_DRIVERS}; do
            (
                echo "[${driver_name}]"
                cd drivers/8.3/srpm/"${driver_name}"
                find ./ -name \*.ko -exec bash -c 'objdump -t "$1" | awk "/UND/{print \"\t\" \$NF}" | sort -u' bash-subshell {} \;
            ) >> "${OUTPUT_FILE}"
        done
fi
