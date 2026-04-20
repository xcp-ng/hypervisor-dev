#!/bin/bash -eu

set -o pipefail

DRIVERS_DIR="$(dirname "$0")/../drivers/"
OUTPUT="$DRIVERS_DIR/README.md"

function get_version() {
    local specfile="$1"
    rpmspec --query --qf '%{Version}-%{Release}\n' "$specfile" 2>/dev/null | head -1 ||:
}

function generate_table() {
    local version_dir="$1"
    local srpm_dir="$version_dir/srpm"
    local metadata_file="$srpm_dir/metadata.yaml"

    # Load metadata once as JSON so per-package lookups use fast jq calls.
    local meta_json="{}"
    [ -f "$metadata_file" ] && \
        meta_json="$(python3 -c "import yaml,json,sys; print(json.dumps(yaml.safe_load(open(sys.argv[1])) or {}))" "$metadata_file")"

    declare -A normal_vers
    declare -A alt_vers
    declare -a all_packages

    for dir in "$srpm_dir"/*/; do
        local dirname
        dirname="$(basename "$dir")"
        local specfile
        specfile="$(find "$dir"/SPECS/ -name \*.spec 2>/dev/null | head -1 ||:)"
        [ -z "$specfile" ] && continue

        local ver
        ver="$(get_version "$specfile")"

        if [[ "$dirname" == *-alt ]]; then
            local pkg="${dirname%-alt}"
            alt_vers["$pkg"]="$ver"
            all_packages+=("$pkg")
        else
            normal_vers["$dirname"]="$ver"
            all_packages+=("$dirname")
        fi
    done

    # Deduplicate and sort package names
    local packages
    packages="$(printf '%s\n' "${all_packages[@]}" | sort -u)"

    echo "| Package | Main driver | Alternate Driver | XS 8.3 Base | XS 8.3 early access |"
    echo "|---------|-------------|------------------|-------------|---------------------|"
    while IFS= read -r pkg; do
        local normal="${normal_vers[$pkg]:-}"
        local alt="${alt_vers[$pkg]:-}"

        if [ -n "$normal" ] && [ -n "$alt" ] && [ "$normal" != "$alt" ]; then
            local newer
            newer="$(printf '%s\n' "$normal" "$alt" | sort -V | tail -1)"
            [ "$newer" = "$normal" ] && normal="$normal ↑"
            [ "$newer" = "$alt"    ] && alt="$alt ↑"
        fi

        local xs_base xs_ea extra=""
        xs_base="$(jq -r --arg p "$pkg" '.[$p].xs_base // ""' <<< "$meta_json")"
        xs_ea="$(jq -r --arg p "$pkg" '.[$p].xs_earlyaccess // ""' <<< "$meta_json")"
        [ "$(jq -r --arg p "$pkg" '.[$p].default_installed // false' <<< "$meta_json")" = "true" ] || extra="📥"

        echo "| $pkg $extra | $normal | $alt | $xs_base | $xs_ea |"
    done <<< "$packages"

}

{
    echo "# Drivers"
    echo ""

    for version_dir in "$DRIVERS_DIR"/*/; do
        local_version="$(basename "$version_dir")"
        echo "- [XCP-ng $local_version](#XCP-ng-$local_version)"
    done

    echo ""

    for version_dir in "$DRIVERS_DIR"/*/; do
        local_version="$(basename "$version_dir")"
        echo "## XCP-ng $local_version"
        echo ""
        generate_table "$version_dir"
        echo ""
    done
} > "$OUTPUT"

echo "Generated $OUTPUT"
