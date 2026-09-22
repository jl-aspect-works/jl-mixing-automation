#!/usr/bin/env bash
# Create a JL Mixing Automation v1.2 project workspace.
#
# Project creation is transactional. The command resolves and validates the
# owning v1.1-schema studio/client records, builds the complete project plus its
# initial revision in a hidden sibling staging directory, validates all
# governing JSON and workflow state, then atomically commits the project.
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${JL_MIXING_HOME:-$(cd "$SCRIPT_DIR/.." && pwd)}"
# shellcheck source=lib/common.sh
. "$APP_ROOT/lib/common.sh"
# shellcheck source=lib/context.sh
. "$APP_ROOT/lib/context.sh"
# shellcheck source=lib/filesystem.sh
. "$APP_ROOT/lib/filesystem.sh"
# shellcheck source=lib/json.sh
. "$APP_ROOT/lib/json.sh"
# shellcheck source=lib/metadata.sh
. "$APP_ROOT/lib/metadata.sh"
# shellcheck source=lib/naming.sh
. "$APP_ROOT/lib/naming.sh"
# shellcheck source=lib/project-state.sh
. "$APP_ROOT/lib/project-state.sh"
# shellcheck source=lib/revision.sh
. "$APP_ROOT/lib/revision.sh"
# shellcheck source=lib/templates.sh
. "$APP_ROOT/lib/templates.sh"
# shellcheck source=lib/transaction.sh
. "$APP_ROOT/lib/transaction.sh"
# shellcheck source=lib/validation.sh
. "$APP_ROOT/lib/validation.sh"

usage() {
    cat <<'USAGE'
Usage:
  new-mix PROJECT_NAME [options]
  new-mix --project PROJECT_NAME [options]

Options:
  --client ID_OR_PATH      Client ID or client-directory path
  --project NAME           Project display name; alternative to PROJECT_NAME
  --project-id ID          Stable project slug (default: derived from name)
  --artist NAME            Artist or program name (default: client artist, then client name)
  --album TITLE            Album or collection title
  --producer NAME          Producer name
  --engineer NAME          Mix engineer
  --bpm NUMBER             Tempo
  --key TEXT               Musical key
  --time-signature TEXT    Time signature
  --sample-rate HZ         Project sample rate
  --bit-depth BITS         Project bit depth
  --file-format FORMAT     WAV or AIFF
  --deadline YYYY-MM-DD    Project deadline
  --deliverables LIST      Comma-separated requested deliverables
  --description TEXT       Creative direction
  --source PATH            Initial client-delivery file or directory
  --cd                     Enter the project directory after creation
  --no-cd                  Remain in the current directory after creation
  --dry-run                Show the planned project without creating it
  -h, --help               Show this help
USAGE
}

removed_option_error() {
    case "$1" in
        --project-type)
            jl_error "--project-type was removed in JL Mixing 1.1."
            jl_error "The v1.1 project manifest no longer stores a project type."
            ;;
        --daw)
            jl_error "--daw was removed in JL Mixing 1.1."
            jl_error "JL Mixing no longer manages DAW identity or configuration."
            ;;
        --template)
            jl_error "--template was removed in JL Mixing 1.1."
            jl_error "Manage native DAW projects and templates directly in 03_DAW_Project/."
            ;;
        --non-interactive)
            jl_error "--non-interactive was removed in JL Mixing 1.1."
            jl_error "new-mix already uses supplied values and inherited defaults without prompting."
            ;;
    esac
    return "$JL_EXIT_ARGUMENTS"
}

# Print one path as a safely single-quoted shell argument. This output is only
# copy-and-paste guidance; JL Mixing never evaluates it internally.
shell_quote_path() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\"'\"'/g")"
}

# Parse a comma-separated deliverables option without silently dropping empty
# values. The user's order is retained because it is meaningful planning data.
parse_deliverables_csv() {
    local csv
    csv="$1"
    jl_json_require_jq || return $?

    printf '%s' "$csv" | jq -R -c -e '
        split(",") as $raw
        | if ($raw | length) == 0 or any($raw[]; test("^[[:space:]]*$")) then
              error("deliverables must not contain empty entries")
          else
              $raw | map(gsub("^[[:space:]]+|[[:space:]]+$"; ""))
          end
        | if length == 0 then error("at least one deliverable is required") else . end
        | if (unique | length) != length then error("duplicate deliverables are not allowed") else . end
    ' 2>/dev/null || {
        jl_error "Invalid --deliverables list: $csv"
        return "$JL_EXIT_VALIDATION"
    }
}

validate_deliverables_json() {
    local values_json deliverable count unique_count
    values_json="$1"
    count="$(printf '%s' "$values_json" | jq -r 'length')" || return $?
    [ "$count" -gt 0 ] || {
        jl_error "At least one requested deliverable is required."
        return "$JL_EXIT_VALIDATION"
    }

    while IFS= read -r deliverable; do
        jl_validate_enum "$deliverable" \
            main_mix instrumental acapella tv_mix performance_mix stems master || {
            jl_error "Unsupported deliverable type: $deliverable"
            return "$JL_EXIT_VALIDATION"
        }
    done <<EOF_DELIVERABLE_VALUES
$(printf '%s' "$values_json" | jq -r '.[]')
EOF_DELIVERABLE_VALUES

    unique_count="$(printf '%s' "$values_json" | jq -r 'unique | length')" || return $?
    if [ "$unique_count" -ne "$count" ]; then
        jl_error "Requested deliverables must be unique."
        return "$JL_EXIT_VALIDATION"
    fi
}

# Validate a real calendar date rather than accepting only a YYYY-MM-DD shape.
validate_deadline() {
    local value
    value="$1"
    jl_require_command python3 "Python 3 is required for date validation." || return $?
    if ! python3 - "$value" <<'PY_DATE'
from datetime import date
import sys

value = sys.argv[1]
try:
    parsed = date.fromisoformat(value)
except ValueError:
    raise SystemExit(5)
if parsed.isoformat() != value:
    raise SystemExit(5)
PY_DATE
    then
        jl_error "Deadline must be a valid calendar date in YYYY-MM-DD form: $value"
        return "$JL_EXIT_VALIDATION"
    fi
}

# Resolve a client by explicit path, stable ID, or current-directory context.
# Explicit paths can be used from outside the studio; stable IDs require an
# otherwise discoverable studio root so the lookup remains unambiguous.
resolve_client_and_studio() {
    local reference reference_seen candidate matches match_count client_file
    reference="$1"
    reference_seen="$2"

    if [ "$reference_seen" -eq 0 ]; then
        client_root="$(jl_context_client_root_v11 "$PWD")" || {
            jl_error "Run new-mix inside a client directory or supply --client CLIENT_ID_OR_PATH."
            return "$JL_EXIT_CONTEXT"
        }
        studio_root="$(jl_context_studio_root_v11 "$client_root")" || return $?
        return 0
    fi

    jl_assert_nonempty "$reference" "client reference" || return $?
    candidate="$(jl_abspath_allow_missing "$reference")" || return $?
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then
        client_root="$(jl_context_resolve_client_v11 "$reference" "$PWD")" || return $?
        studio_root="$(jl_context_studio_root_v11 "$client_root")" || return $?
        return 0
    fi

    if ! jl_validate_slug "$reference"; then
        jl_error "Client ID must be a lowercase slug, or --client must identify an existing path: $reference"
        return "$JL_EXIT_VALIDATION"
    fi

    studio_root="$(jl_context_studio_root_v11 "$PWD")" || {
        jl_error "A studio context is required to resolve client ID '$reference'."
        return "$JL_EXIT_CONTEXT"
    }
    matches="$(find "$studio_root/Clients" -mindepth 2 -maxdepth 2 \
        -type f -name client.json -print 2>/dev/null |
        while IFS= read -r client_file; do
            if [ "$(jl_json_get_optional "$client_file" '.client_id' '')" = "$reference" ]; then
                dirname "$client_file"
            fi
            :
        done)"
    match_count="$(printf '%s\n' "$matches" | sed '/^$/d' | wc -l | tr -d ' ')"
    if [ "$match_count" = 1 ]; then
        client_root="$matches"
        return 0
    fi
    if [ "$match_count" -gt 1 ]; then
        jl_error "Multiple clients use the ID '$reference'."
        return "$JL_EXIT_VALIDATION"
    fi

    jl_error "Client not found: $reference"
    return "$JL_EXIT_CONTEXT"
}

# Write a deterministic source-import plan. The scan rejects symbolic links,
# special filesystem objects, control characters, and case-insensitive path
# collisions before the project staging directory exists.
scan_source_to_plan() {
    local source plan_file python_command
    source="$1"
    plan_file="$2"
    python_command="$(jl_json_validator_python)" || {
        jl_error "Python 3 is required for source-import validation."
        return "$JL_EXIT_CONFIG"
    }
    "$python_command" "$APP_ROOT/tools/import-project-source.py"         scan "$source" "$plan_file" || {
        jl_error "Unable to validate source import: $source"
        return "$JL_EXIT_VALIDATION"
    }
}

# Copy exactly the previously scanned source plan into the empty immutable
# Original_Delivery staging directory. The helper rescans before copying so a
# changed source tree cannot silently alter the import.
copy_source_from_plan() {
    local source destination plan_file python_command
    source="$1"
    destination="$2"
    plan_file="$3"
    python_command="$(jl_json_validator_python)" || {
        jl_error "Python 3 is required for source importing."
        return "$JL_EXIT_CONFIG"
    }
    "$python_command" "$APP_ROOT/tools/import-project-source.py"         copy "$source" "$destination" "$plan_file" || {
        jl_error "Source import failed: $source"
        return "$JL_EXIT_VALIDATION"
    }
}

# Write the committed project destination to the private shell-wrapper result
# file. The result file is created securely by the sourced shell wrapper.
write_directory_result() {
    local result_file destination
    result_file="$1"
    destination="$2"

    jl_path_validate_absolute "$result_file" || return $?
    if [ ! -f "$result_file" ] || [ -L "$result_file" ] || [ ! -w "$result_file" ]; then
        jl_error "Shell-integration result file is missing or unsafe: $result_file"
        return "$JL_EXIT_UNSAFE"
    fi
    printf '%s\n' "$destination" > "$result_file" || {
        jl_error "Unable to write shell-integration directory result: $result_file"
        return "$JL_EXIT_GENERAL"
    }
}

client_ref=""
project_name=""
project_id=""
artist=""
album=""
producer=""
engineer=""
bpm=""
musical_key=""
time_signature=""
sample_rate=""
bit_depth=""
file_format=""
deadline=""
deliverables_csv=""
description=""
source_path=""
client_seen=0
project_seen=0
positional_project_seen=0
project_id_seen=0
artist_seen=0
engineer_seen=0
sample_rate_seen=0
bit_depth_seen=0
file_format_seen=0
deliverables_seen=0
source_seen=0
cd_enabled_seen=0
cd_disabled_seen=0
dry_run=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --client)
            [ "$#" -ge 2 ] || jl_die "--client requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            client_ref="$2"
            client_seen=1
            shift 2
            ;;
        --project)
            [ "$#" -ge 2 ] || jl_die "--project requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            # A project name may use either supported form, but never both.
            if [ "$positional_project_seen" -eq 1 ]; then
                jl_die "Project name cannot be specified both positionally and with --project." "$JL_EXIT_ARGUMENTS"
                exit $?
            fi
            project_name="$2"
            project_seen=1
            shift 2
            ;;
        --project-id)
            [ "$#" -ge 2 ] || jl_die "--project-id requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            project_id="$2"
            project_id_seen=1
            shift 2
            ;;
        --artist)
            [ "$#" -ge 2 ] || jl_die "--artist requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            artist="$2"
            artist_seen=1
            shift 2
            ;;
        --album)
            [ "$#" -ge 2 ] || jl_die "--album requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            album="$2"
            shift 2
            ;;
        --producer)
            [ "$#" -ge 2 ] || jl_die "--producer requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            producer="$2"
            shift 2
            ;;
        --engineer)
            [ "$#" -ge 2 ] || jl_die "--engineer requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            engineer="$2"
            engineer_seen=1
            shift 2
            ;;
        --bpm)
            [ "$#" -ge 2 ] || jl_die "--bpm requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            bpm="$2"
            shift 2
            ;;
        --key)
            [ "$#" -ge 2 ] || jl_die "--key requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            musical_key="$2"
            shift 2
            ;;
        --time-signature)
            [ "$#" -ge 2 ] || jl_die "--time-signature requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            time_signature="$2"
            shift 2
            ;;
        --sample-rate)
            [ "$#" -ge 2 ] || jl_die "--sample-rate requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            sample_rate="$2"
            sample_rate_seen=1
            shift 2
            ;;
        --bit-depth)
            [ "$#" -ge 2 ] || jl_die "--bit-depth requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            bit_depth="$2"
            bit_depth_seen=1
            shift 2
            ;;
        --file-format)
            [ "$#" -ge 2 ] || jl_die "--file-format requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            file_format="$2"
            file_format_seen=1
            shift 2
            ;;
        --deadline)
            [ "$#" -ge 2 ] || jl_die "--deadline requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            deadline="$2"
            shift 2
            ;;
        --deliverables)
            [ "$#" -ge 2 ] || jl_die "--deliverables requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            deliverables_csv="$2"
            deliverables_seen=1
            shift 2
            ;;
        --description)
            [ "$#" -ge 2 ] || jl_die "--description requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            description="$2"
            shift 2
            ;;
        --source)
            [ "$#" -ge 2 ] || jl_die "--source requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            source_path="$2"
            source_seen=1
            shift 2
            ;;
        --cd)
            cd_enabled_seen=1
            shift
            ;;
        --no-cd)
            cd_disabled_seen=1
            shift
            ;;
        --dry-run)
            dry_run=1
            shift
            ;;
        --project-type|--daw|--template|--non-interactive)
            removed_option_error "$1"
            exit $?
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --*)
            jl_die "Unknown option: $1" "$JL_EXIT_ARGUMENTS"
            exit $?
            ;;
        *)
            # Accept exactly one positional project name and feed it into the
            # same validation and creation path used by --project.
            if [ "$project_seen" -eq 1 ]; then
                jl_die "Project name cannot be specified both positionally and with --project." "$JL_EXIT_ARGUMENTS"
                exit $?
            fi
            if [ "$positional_project_seen" -eq 1 ]; then
                jl_die "Unexpected positional argument: $1" "$JL_EXIT_ARGUMENTS"
                exit $?
            fi
            project_name="$1"
            positional_project_seen=1
            shift
            ;;
    esac
done

if [ "$cd_enabled_seen" -eq 1 ] && [ "$cd_disabled_seen" -eq 1 ]; then
    jl_error "--cd and --no-cd cannot be used together."
    exit "$JL_EXIT_ARGUMENTS"
fi
if [ "$dry_run" -eq 1 ] && { [ "$cd_enabled_seen" -eq 1 ] || [ "$cd_disabled_seen" -eq 1 ]; }; then
    jl_error "--cd and --no-cd cannot be used with --dry-run."
    exit "$JL_EXIT_ARGUMENTS"
fi

if [ "$project_seen" -eq 0 ] && [ "$positional_project_seen" -eq 0 ]; then
    jl_error "A project name is required. Supply it positionally or with --project."
    exit "$JL_EXIT_ARGUMENTS"
fi
project_name="$(jl_trim "$project_name")"
artist="$(jl_trim "$artist")"
album="$(jl_trim "$album")"
producer="$(jl_trim "$producer")"
engineer="$(jl_trim "$engineer")"
musical_key="$(jl_trim "$musical_key")"
time_signature="$(jl_trim "$time_signature")"
description="$(jl_trim "$description")"
jl_assert_nonempty "$project_name" "project name" || exit $?
project_folder_name="$(jl_sanitize_folder_name "$project_name")" || exit $?

if [ "$project_id_seen" -eq 0 ]; then
    project_id="$(jl_project_id_from_name "$project_name")" || exit $?
fi
if ! jl_validate_slug "$project_id"; then
    jl_error "Project ID must be a lowercase slug using single hyphens: $project_id"
    exit "$JL_EXIT_VALIDATION"
fi

if [ -n "$bpm" ]; then
    printf '%s' "$bpm" | grep -Eq '^[0-9]+([.][0-9]+)?$' || {
        jl_error "BPM must be a positive number: $bpm"
        exit "$JL_EXIT_VALIDATION"
    }
    awk "BEGIN { exit !($bpm > 0) }" || {
        jl_error "BPM must be greater than zero: $bpm"
        exit "$JL_EXIT_VALIDATION"
    }
fi
if [ -n "$deadline" ]; then
    validate_deadline "$deadline" || exit $?
fi
if [ "$sample_rate_seen" -eq 1 ]; then
    jl_validate_sample_rate "$sample_rate" || {
        jl_error "Unsupported sample rate: $sample_rate"
        exit "$JL_EXIT_VALIDATION"
    }
fi
if [ "$bit_depth_seen" -eq 1 ]; then
    jl_validate_bit_depth "$bit_depth" || {
        jl_error "Unsupported bit depth: $bit_depth"
        exit "$JL_EXIT_VALIDATION"
    }
fi
if [ "$file_format_seen" -eq 1 ]; then
    file_format="$(printf '%s' "$file_format" | tr '[:lower:]' '[:upper:]')"
    jl_validate_file_format "$file_format" || {
        jl_error "Unsupported file format: $file_format"
        exit "$JL_EXIT_VALIDATION"
    }
fi
if [ "$deliverables_seen" -eq 1 ]; then
    deliverables_json="$(parse_deliverables_csv "$deliverables_csv")" || exit $?
    validate_deliverables_json "$deliverables_json" || exit $?
fi

resolve_client_and_studio "$client_ref" "$client_seen" || exit $?
studio_file="$studio_root/Studio/studio.json"
client_file="$client_root/client.json"

jl_json_validate_local_document \
    "$studio_file" studio.schema.json mixing-studio 1.1.0 >/dev/null || exit $?
jl_metadata_validate_v11 "$studio_file" mixing-studio mutable || exit $?
jl_json_validate_local_document \
    "$client_file" client.schema.json mixing-client 1.1.0 >/dev/null || exit $?
jl_metadata_validate_v11 "$client_file" mixing-client mutable || exit $?
jl_json_validate_unique_uuids "$studio_root" || exit $?

clients_root="$studio_root/Clients"
projects_root="$client_root/Projects"
case "$client_root" in
    "$clients_root"/*) ;;
    *)
        jl_error "Selected client is not owned by the resolved studio: $client_root"
        exit "$JL_EXIT_CONTEXT"
        ;;
esac
jl_fs_assert_no_symlink_components "$studio_root" "$client_root" || exit $?
if ! jl_fs_is_directory_no_symlink "$projects_root"; then
    jl_error "Client Projects directory is missing or unsafe: $projects_root"
    exit "$JL_EXIT_CONTEXT"
fi
if [ ! -w "$projects_root" ] || [ ! -x "$projects_root" ]; then
    jl_error "Client Projects directory is not writable: $projects_root"
    exit "$JL_EXIT_UNSAFE"
fi
jl_fs_assert_no_symlink_components "$studio_root" "$projects_root" || exit $?

client_name="$(jl_json_get "$client_file" '.client_name')"
client_id="$(jl_json_get "$client_file" '.client_id')"
client_document_id="$(jl_json_get "$client_file" '.metadata.document_id')"

if [ "$artist_seen" -eq 0 ]; then
    artist="$(jl_trim "$(jl_json_get_optional "$client_file" '.defaults.artist' '')")"
    # A client display name is the final safe default when the optional artist
    # default was never configured. The client snapshot remains unchanged.
    [ -n "$artist" ] || artist="$client_name"
else
    artist="$(jl_trim "$artist")"
    if [ -z "$artist" ]; then
        jl_error "Artist must not be empty when --artist is supplied."
        exit "$JL_EXIT_VALIDATION"
    fi
fi
if [ "$engineer_seen" -eq 0 ]; then
    engineer="$(jl_json_get_optional "$studio_file" '.defaults.mix_engineer' '')"
fi
engineer="$(jl_trim "$engineer")"

if [ "$sample_rate_seen" -eq 0 ]; then
    sample_rate="$(jl_json_get_optional "$client_file" '.defaults.audio.sample_rate' '')"
    [ -n "$sample_rate" ] || sample_rate="$(jl_json_get "$studio_file" '.defaults.audio.sample_rate')"
fi
if [ "$bit_depth_seen" -eq 0 ]; then
    bit_depth="$(jl_json_get_optional "$client_file" '.defaults.audio.bit_depth' '')"
    [ -n "$bit_depth" ] || bit_depth="$(jl_json_get "$studio_file" '.defaults.audio.bit_depth')"
fi
if [ "$file_format_seen" -eq 0 ]; then
    file_format="$(jl_json_get_optional "$client_file" '.defaults.audio.file_format' '')"
    [ -n "$file_format" ] || file_format="$(jl_json_get "$studio_file" '.defaults.audio.file_format')"
fi
file_format="$(printf '%s' "$file_format" | tr '[:lower:]' '[:upper:]')"
jl_validate_sample_rate "$sample_rate" || { jl_error "Unsupported sample rate: $sample_rate"; exit "$JL_EXIT_VALIDATION"; }
jl_validate_bit_depth "$bit_depth" || { jl_error "Unsupported bit depth: $bit_depth"; exit "$JL_EXIT_VALIDATION"; }
jl_validate_file_format "$file_format" || { jl_error "Unsupported file format: $file_format"; exit "$JL_EXIT_VALIDATION"; }

delivery_method="$(jl_json_get_optional "$client_file" '.defaults.delivery.method' '')"
[ -n "$delivery_method" ] || delivery_method="$(jl_json_get "$studio_file" '.defaults.delivery.method')"
delivery_method="$(jl_trim "$delivery_method")"
jl_assert_nonempty "$delivery_method" "delivery method" || exit $?
if [ "$deliverables_seen" -eq 0 ]; then
    deliverables_json="$(jl_json_get_json "$client_file" '.defaults.delivery.requested_deliverables')"
    if [ "$(printf '%s' "$deliverables_json" | jq -r 'length')" -eq 0 ]; then
        deliverables_json="$(jl_json_get_json "$studio_file" '.defaults.delivery.requested_deliverables')"
    fi
    validate_deliverables_json "$deliverables_json" || exit $?
fi

jl_validate_project_id_available "$client_root" "$project_id" || exit $?
jl_fs_assert_no_case_insensitive_child_collision "$projects_root" "$project_folder_name" || exit $?
project_root="$projects_root/$project_folder_name"
initial_revision_number=1
initial_revision_description="Initial mix"
initial_revision_name="$(jl_revision_name "$initial_revision_number")"
initial_revision_root="$project_root/04_Revisions/$initial_revision_name"
if [ -e "$project_root" ] || [ -L "$project_root" ]; then
    jl_error "Project destination already exists: $project_root"
    exit "$JL_EXIT_UNSAFE"
fi

studio_default_cd="$(jq -r '.cli.change_directory_after_create' "$studio_file")"
effective_cd=0
if [ "$cd_enabled_seen" -eq 1 ]; then
    effective_cd=1
elif [ "$cd_disabled_seen" -eq 1 ]; then
    effective_cd=0
elif [ "$studio_default_cd" = true ]; then
    effective_cd=1
fi

stage_root=""
source_plan_dir=""
source_plan_file=""
cleanup_paths() {
    local status
    status=$?
    if [ -n "$stage_root" ] && { [ -e "$stage_root" ] || [ -L "$stage_root" ]; }; then
        jl_fs_remove_entry_no_follow "$stage_root" || true
    fi
    if [ -n "$source_plan_dir" ] && { [ -e "$source_plan_dir" ] || [ -L "$source_plan_dir" ]; }; then
        jl_fs_remove_entry_no_follow "$source_plan_dir" || true
    fi
    return "$status"
}
trap cleanup_paths EXIT
trap 'exit 1' HUP INT TERM

if [ "$source_seen" -eq 1 ]; then
    jl_assert_nonempty "$source_path" "source path" || exit $?
    if [ -L "$source_path" ]; then
        jl_error "Symbolic-link source paths are not allowed: $source_path"
        exit "$JL_EXIT_UNSAFE"
    fi
    source_path="$(jl_abspath_allow_missing "$source_path")" || exit $?
    if ! jl_fs_is_regular_file_no_symlink "$source_path" && ! jl_fs_is_directory_no_symlink "$source_path"; then
        jl_error "Source must be an existing regular file or directory: $source_path"
        exit "$JL_EXIT_VALIDATION"
    fi
    if jl_fs_is_directory_no_symlink "$source_path"; then
        case "$projects_root/" in
            "$source_path"/*)
                jl_error "Source directory cannot contain the client Projects directory: $source_path"
                exit "$JL_EXIT_UNSAFE"
                ;;
        esac
    fi
    source_plan_dir="$(jl_mktemp_dir jl-mixing-new-mix-source)" || exit $?
    source_plan_file="$source_plan_dir/plan.json"
    scan_source_to_plan "$source_path" "$source_plan_file" || exit $?
fi

print_summary() {
    local heading source_display
    heading="$1"
    source_display="${source_path:-<none>}"

    printf '%s\n\n' "$heading"
    printf 'Client:                     %s (%s)\n' "$client_name" "$client_id"
    printf 'Project:                    %s\n' "$project_name"
    printf 'Project ID:                 %s\n' "$project_id"
    printf 'Project folder:             %s\n' "$project_root"
    printf 'Artist:                     %s\n' "$artist"
    printf 'Engineer:                   %s\n' "${engineer:-<not set>}"
    printf 'Audio format:               %s Hz / %s-bit / %s\n' "$sample_rate" "$bit_depth" "$file_format"
    printf 'Delivery method:            %s\n' "$delivery_method"
    printf 'Requested deliverables:     %s\n' "$(printf '%s' "$deliverables_json" | jq -r 'join(", ")')"
    printf 'Source:                     %s\n' "$source_display"
    printf 'Initial state:              In progress\n'
    printf 'Current revision:           %s\n' "$initial_revision_number"
    printf 'Initial revision:           %s\n' "$initial_revision_root"
    if [ "$effective_cd" -eq 1 ]; then
        printf 'Automatic directory change: enabled\n'
    else
        printf 'Automatic directory change: disabled\n'
    fi
}

if [ "$dry_run" -eq 1 ]; then
    print_summary "Dry run — no changes made."
    cat <<'EOF_PLAN'

Would create:
  00_Admin/
  01_Client_Files/Original_Delivery/
  01_Client_Files/References/
  01_Client_Files/Documentation/
  02_Audio_Preparation/Working_Audio/
  02_Audio_Preparation/Rejected_Files/
  03_DAW_Project/
  04_Revisions/
  04_Revisions/Revision_01/
  04_Revisions/Revision_01/Revision_Notes.md
  05_Final_Delivery/Stems/
  06_Recall/External_Files/
  06_Recall/Screenshots/
EOF_PLAN
    if [ -n "$source_plan_file" ]; then
        printf '\nWould copy into 01_Client_Files/Original_Delivery/:\n'
        if [ "$(jq -r '.entries | length' "$source_plan_file")" -eq 0 ]; then
            printf '  <source directory is empty>\n'
        else
            jq -r '.entries[] | "  " + .path + (if .type == "directory" then "/" else "" end)' "$source_plan_file"
        fi
    fi
    printf '\nAfter creation:\n  cd '
    shell_quote_path "$project_root"
    printf '\n  approve-mix\n'
    exit 0
fi

project_schema="$(jl_json_schema_path project-manifest.schema.json)" || exit $?
snapshot_schema="$(jl_json_schema_path client-profile-snapshot.schema.json)" || exit $?
# Validate the application release version before creating transactional output.
# Document schema compatibility is checked separately against schema_version.
jl_software_version >/dev/null || exit $?

stage_root="$(jl_txn_stage_directory_near "$project_root")" || exit $?
chmod 755 "$stage_root"
mkdir -p \
    "$stage_root/00_Admin" \
    "$stage_root/01_Client_Files/Original_Delivery" \
    "$stage_root/01_Client_Files/References" \
    "$stage_root/01_Client_Files/Documentation" \
    "$stage_root/02_Audio_Preparation/Working_Audio" \
    "$stage_root/02_Audio_Preparation/Rejected_Files" \
    "$stage_root/03_DAW_Project" \
    "$stage_root/04_Revisions/$initial_revision_name" \
    "$stage_root/05_Final_Delivery/Stems" \
    "$stage_root/06_Recall/External_Files" \
    "$stage_root/06_Recall/Screenshots"

created_at="$(jl_now_iso8601)"
project_document_id="$(jl_uuid)" || exit $?
snapshot_document_id="$(jl_uuid)" || exit $?
while [ "$snapshot_document_id" = "$project_document_id" ]; do
    snapshot_document_id="$(jl_uuid)" || exit $?
done
revision_id="$(jl_uuid)" || exit $?
while [ "$revision_id" = "$project_document_id" ] || [ "$revision_id" = "$snapshot_document_id" ]; do
    revision_id="$(jl_uuid)" || exit $?
done
jl_json_assert_document_id_available "$studio_root" "$project_document_id" || exit $?
jl_json_assert_document_id_available "$studio_root" "$snapshot_document_id" || exit $?
jl_json_assert_uuid_available "$studio_root" "$revision_id" || exit $?

project_metadata="$(jl_metadata_create_v11_mutable \
    mixing-project 1.1.0 "$project_document_id" "$created_at")" || exit $?
snapshot_metadata="$(jl_metadata_create_v11_immutable \
    mixing-client-profile-snapshot 1.1.0 "$snapshot_document_id" "$created_at")" || exit $?
client_defaults_json="$(jl_json_get_json "$client_file" '.defaults')"
if [ -n "$bpm" ]; then bpm_json="$bpm"; else bpm_json=null; fi
if [ -n "$deadline" ]; then
    deadline_json="$(jq -Rn --arg value "$deadline" '$value')"
else
    deadline_json=null
fi

staged_project_file="$stage_root/00_Admin/project-manifest.json"
staged_snapshot_file="$stage_root/00_Admin/client-profile-snapshot.json"

jq -n \
    --argjson metadata "$project_metadata" \
    --arg project_id "$project_id" \
    --arg project_name "$project_name" \
    --arg client_document_id "$client_document_id" \
    --arg client_id "$client_id" \
    --arg artist "$artist" \
    --arg album "$album" \
    --arg producer "$producer" \
    --arg mix_engineer "$engineer" \
    --argjson bpm "$bpm_json" \
    --arg key "$musical_key" \
    --arg time_signature "$time_signature" \
    --argjson sample_rate "$sample_rate" \
    --argjson bit_depth "$bit_depth" \
    --arg file_format "$file_format" \
    --arg delivery_method "$delivery_method" \
    --argjson deliverables "$deliverables_json" \
    --argjson deadline "$deadline_json" \
    --arg creative_direction "$description" \
    '{
        metadata: $metadata,
        project_id: $project_id,
        project_name: $project_name,
        client: {
            client_document_id: $client_document_id,
            client_id: $client_id
        },
        artist: $artist,
        album: $album,
        producer: $producer,
        mix_engineer: $mix_engineer,
        music: {
            bpm: $bpm,
            key: $key,
            time_signature: $time_signature
        },
        audio: {
            sample_rate: $sample_rate,
            bit_depth: $bit_depth,
            file_format: $file_format
        },
        delivery: {
            method: $delivery_method,
            requested_deliverables: $deliverables
        },
        schedule: {deadline: $deadline},
        creative_direction: $creative_direction,
        state: {
            current_revision: 0,
            approved_revision: null,
            delivered_revision: null
        },
        revisions: []
    }' > "$staged_project_file" || exit $?
chmod 644 "$staged_project_file"

# Reuse the canonical revision helper so initial and later revisions share the
# same manifest record structure and pointer update behavior.
jl_revision_append \
    "$staged_project_file" "$initial_revision_description" \
    "$initial_revision_number" "$created_at" "$revision_id" || exit $?

jq -n \
    --argjson metadata "$snapshot_metadata" \
    --arg client_document_id "$client_document_id" \
    --arg client_id "$client_id" \
    --arg client_name "$client_name" \
    --argjson defaults "$client_defaults_json" \
    '{
        metadata: $metadata,
        source_client: {
            client_document_id: $client_document_id,
            client_id: $client_id,
            client_name: $client_name
        },
        defaults: $defaults
    }' > "$staged_snapshot_file" || exit $?
chmod 644 "$staged_snapshot_file"

jl_template_render "$APP_ROOT/templates/Intake_Report.md" \
    "$stage_root/00_Admin/Intake_Report.md" || exit $?
jl_template_render "$APP_ROOT/templates/Project_Notes.md" \
    "$stage_root/00_Admin/Project_Notes.md" || exit $?
jl_template_render "$APP_ROOT/templates/Preparation_Report.md" \
    "$stage_root/02_Audio_Preparation/Preparation_Report.md" || exit $?
jl_template_render "$APP_ROOT/templates/Revision_Notes.md" \
    "$stage_root/04_Revisions/$initial_revision_name/Revision_Notes.md" \
    REVISION_NUMBER "$initial_revision_number" \
    REVISION_DESCRIPTION "$initial_revision_description" || exit $?
jl_template_render "$APP_ROOT/templates/Delivery_Notes.md" \
    "$stage_root/05_Final_Delivery/Delivery_Notes.md" || exit $?
jl_template_render "$APP_ROOT/templates/Recall_Sheet.md" \
    "$stage_root/06_Recall/Recall_Sheet.md" || exit $?

if [ -n "$source_plan_file" ]; then
    copy_source_from_plan \
        "$source_path" "$stage_root/01_Client_Files/Original_Delivery" "$source_plan_file" || exit $?
fi

jl_json_validate_schema "$project_schema" "$staged_project_file" >/dev/null || exit $?
jl_metadata_validate_v11 "$staged_project_file" mixing-project mutable || exit $?
jl_json_validate_schema "$snapshot_schema" "$staged_snapshot_file" >/dev/null || exit $?
jl_metadata_validate_v11 "$staged_snapshot_file" mixing-client-profile-snapshot immutable || exit $?

# Cross-document validation remains explicit because JSON Schema cannot verify
# identity relationships between the owning client, snapshot, and project.
if [ "$(jl_json_get "$staged_snapshot_file" '.source_client.client_document_id')" != "$client_document_id" ] || \
   [ "$(jl_json_get "$staged_snapshot_file" '.source_client.client_id')" != "$client_id" ]; then
    jl_error "Generated client snapshot does not match the owning client."
    exit "$JL_EXIT_VALIDATION"
fi
if [ "$(jl_json_get "$staged_project_file" '.client.client_document_id')" != "$client_document_id" ] || \
   [ "$(jl_json_get "$staged_project_file" '.client.client_id')" != "$client_id" ]; then
    jl_error "Generated project manifest does not match the owning client."
    exit "$JL_EXIT_VALIDATION"
fi
jl_project_validate_state "$stage_root" || exit $?

jl_txn_commit_new_directory "$stage_root" "$project_root" || exit $?
stage_root=""

result_written=0
if [ "$effective_cd" -eq 1 ] && [ -n "${JL_MIXING_CD_RESULT_FILE:-}" ]; then
    write_directory_result "$JL_MIXING_CD_RESULT_FILE" "$project_root" || {
        jl_error "Project creation succeeded, but automatic directory-change setup failed."
        {
            printf 'Run:\n  cd '
            shell_quote_path "$project_root"
            printf '\n'
        } >&2
        exit "$JL_EXIT_GENERAL"
    }
    result_written=1
fi

print_summary "Project created successfully."
printf 'Manifest:                    %s\n' "$project_root/00_Admin/project-manifest.json"
printf 'Client snapshot:             %s\n' "$project_root/00_Admin/client-profile-snapshot.json"

if [ "$effective_cd" -eq 1 ] && [ "$result_written" -eq 0 ]; then
    cat <<'EOF_WARNING'

Automatic directory change could not be performed because JL Mixing shell
integration is not active.
EOF_WARNING
fi

printf '\nNext:\n'
if [ "$effective_cd" -eq 0 ] || [ "$result_written" -eq 0 ]; then
    printf '  cd '
    shell_quote_path "$project_root"
    printf '\n'
fi
printf '  approve-mix\n'
