#!/bin/bash -eu

set -o pipefail

DRIVERS_DIR="$(dirname "$0")/../drivers/"
DRIVER_DISKS_DIR="$(dirname "$0")/../driver-disks/"
OUTPUT="$DRIVERS_DIR/README.md"

function get_driver_disk_icon() {
    local pkg="$1" ver="$2" xcpng_ver="$3"
    local cfgs=("$DRIVER_DISKS_DIR"/*-"${xcpng_ver}".cfg)

    local base_url="https://updates.xcp-ng.org/isos/drivers/8.x"
    local cfg rpm_file pack_build iso_stem

    cfg_iso_link() {
        rpm_file="$(grep -F 'RPM_FILE='   "$1" | sed 's/^RPM_FILE="\(.*\)"$/\1/')"
        pack_build="$(grep -F 'PACK_BUILD=' "$1" | sed 's/^PACK_BUILD="\(.*\)"$/\1/')"
        iso_stem="${rpm_file%.*.rpm}"
        iso_stem="${iso_stem%-*}+${iso_stem##*-}"
        echo "[${2}](${base_url}/${iso_stem}+${pack_build}.iso)"
    }

    # Exact version matches get an ISO icon
    for cfg in "${cfgs[@]}"; do
        grep -qF "RPM_FILE=\"${pkg}-${ver}.xcpng${xcpng_ver}." "$cfg" 2>/dev/null || continue
        cfg_iso_link "$cfg" "💿"
        return 0
    done

    # Package name match with differing version get a disquette
    for cfg in "${cfgs[@]}"; do
        grep -qF "RPM_FILE=\"${pkg}-" "$cfg" 2>/dev/null || continue

	# Make sure we are not loose-matching on the -alt version
        grep -qF "RPM_FILE=\"${pkg}-alt-" "$cfg" 2>/dev/null && continue
        cfg_iso_link "$cfg" "💾"
        return 0
    done
}

function get_version() {
    local specfile="$1"
    rpmspec --query --qf '%{Version}-%{Release}\n' "$specfile" 2>/dev/null | head -1 ||:
}

function generate_table() {
    local version_dir="$1"
    local xcpng_version
    xcpng_version="$(basename "$version_dir")"
    local srpm_dir="$version_dir/srpm"
    local source_dir="$version_dir/source"
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
        local normal_raw="${normal_vers[$pkg]:-}" alt_raw="${alt_vers[$pkg]:-}"
        local normal="$normal_raw" alt="$alt_raw"

	[ -n "$normal_raw" ] && {
	    normal="[$normal_raw](https://github.com/xcp-ng-rpms/$pkg/blob/$(git -C "$srpm_dir/$pkg" rev-parse HEAD))"
	    normal="[📜](https://github.com/xcp-ng-rpms/$pkg/blob/$(git -C "$source_dir/$pkg" rev-parse HEAD)) $normal"
	}
	[ -n "$alt_raw" ] && {
	    alt="[$alt_raw](https://github.com/xcp-ng-rpms/$pkg/blob/$(git -C "$srpm_dir/$pkg-alt" rev-parse HEAD))"
	    alt="[📜](https://github.com/xcp-ng-rpms/$pkg/blob/$(git -C "$source_dir/$pkg-alt" rev-parse HEAD)) $alt"
	}

        if [ -n "$normal_raw" ] && [ -n "$alt_raw" ] && [ "$normal_raw" != "$alt_raw" ]; then
            local newer
            newer="$(printf '%s\n' "$normal_raw" "$alt_raw" | sort -V | tail -1)"
            [ "$newer" = "$normal_raw" ] && normal="$normal ↑"
            [ "$newer" = "$alt_raw"    ] && alt="$alt ↑"
        fi

	normal="$normal $(get_driver_disk_icon "$pkg" "$normal_raw" "$xcpng_version") "
	alt="$alt $(get_driver_disk_icon "${pkg}-alt" "$alt_raw" "$xcpng_version")"

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
	echo "> [!NOTE]"
	echo "> 📥 other driver (needs manual installation)</br>"
	echo "> 📜 driver source code</br>"
	echo "> 💿 driver disk available for this exact version</br>"
	echo "> 💾 driver disk available for an older version</br>"
	echo "> </br>"
	echo "> ↑ more recent version between main/alternate</br>"
	echo ""

        generate_table "$version_dir"
        echo ""
    done
} > "$OUTPUT"

echo "Generated $OUTPUT"
