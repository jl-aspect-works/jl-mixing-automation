#!/usr/bin/env bash
# Shared client-creation command implementation.
#
# This file is sourced by the human-facing new-client launcher and provides the
# behavior-preserving foundation for the Automation API client.create route.
# Keeping the implementation in-process prevents the API dispatcher from
# wrapping the public command as a subprocess.

if [ "${JL_MIXING_CLIENT_CREATE_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_CLIENT_CREATE_LOADED=1

jl_client_create_command() {

JL_CLIENT_CREATE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${JL_MIXING_HOME:-$(cd "$JL_CLIENT_CREATE_LIB_DIR/.." && pwd)}"
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
# shellcheck source=lib/templates.sh
. "$APP_ROOT/lib/templates.sh"
# shellcheck source=lib/transaction.sh
. "$APP_ROOT/lib/transaction.sh"
# shellcheck source=lib/validation.sh
. "$APP_ROOT/lib/validation.sh"

usage() {
    cat <<'USAGE'
Usage: new-client CLIENT_ID [options]

Options:
  --name NAME             Display name (default: title-cased client ID)
  --artist NAME           Default artist or program name
  --sample-rate HZ        Default project sample rate
  --bit-depth BITS        Default project bit depth
  --file-format FORMAT    Default project format: WAV or AIFF
  --delivery-method TEXT  Default delivery method
  --deliverables LIST     Comma-separated requested deliverables
  --cd                    Enter the new client directory after creation
  --no-cd                 Remain in the current directory after creation
  --dry-run               Show the planned client without creating it
  -h, --help              Show this help
USAGE
}

removed_option_error() {
    case "$1" in
        --revision-limit)
            jl_error "--revision-limit was removed in JL Mixing 1.1."
            jl_error "The v1.1 revision workflow has no included-revision limit."
            ;;
        --non-interactive)
            jl_error "--non-interactive was removed in JL Mixing 1.1."
            jl_error "new-client already uses supplied values and inherited defaults without prompting."
            ;;
    esac
    return "$JL_EXIT_ARGUMENTS"
}

# Print one path as a safely single-quoted shell argument. This output is only
# guidance for the user; commands never evaluate it internally.
shell_quote_path() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\"'\"'/g")"
}

# Parse a comma-separated deliverables option without silently dropping empty
# entries. The canonical order supplied by the user is preserved.
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


# Validate a non-empty requested-deliverables array against the canonical v1.1
# enum while preserving the caller's array order.
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

# Write the committed destination to the private shell-wrapper result file.
# The file must already be a writable, absolute, non-symlink regular file.
write_directory_result() {
    local result_file destination
    result_file="$1"
    destination="$2"

    jl_path_validate_absolute "$result_file" || {
        jl_error "Shell-integration result path must be absolute: $result_file"
        return "$JL_EXIT_UNSAFE"
    }
    if [ ! -f "$result_file" ] || [ -L "$result_file" ] || [ ! -w "$result_file" ]; then
        jl_error "Shell-integration result file is missing or unsafe: $result_file"
        return "$JL_EXIT_UNSAFE"
    fi
    printf '%s\n' "$destination" > "$result_file" || {
        jl_error "Unable to write shell-integration directory result: $result_file"
        return "$JL_EXIT_GENERAL"
    }
}

client_id=""
client_name=""
artist_name=""
sample_rate=""
bit_depth=""
file_format=""
delivery_method=""
deliverables_csv=""
name_seen=0
sample_rate_seen=0
bit_depth_seen=0
file_format_seen=0
delivery_method_seen=0
deliverables_seen=0
cd_enabled_seen=0
cd_disabled_seen=0
dry_run=0

if [ "$#" -gt 0 ]; then
    case "$1" in
        -*) ;;
        *) client_id="$1"; shift ;;
    esac
fi

while [ "$#" -gt 0 ]; do
    case "$1" in
        --name)
            [ "$#" -ge 2 ] || jl_die "--name requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            client_name="$2"
            name_seen=1
            shift 2
            ;;
        --artist)
            [ "$#" -ge 2 ] || jl_die "--artist requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            artist_name="$2"
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
        --delivery-method)
            [ "$#" -ge 2 ] || jl_die "--delivery-method requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            delivery_method="$2"
            delivery_method_seen=1
            shift 2
            ;;
        --deliverables)
            [ "$#" -ge 2 ] || jl_die "--deliverables requires a value." "$JL_EXIT_ARGUMENTS" || exit $?
            deliverables_csv="$2"
            deliverables_seen=1
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
        --revision-limit|--non-interactive)
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
            jl_die "Unexpected positional argument: $1" "$JL_EXIT_ARGUMENTS"
            exit $?
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

jl_assert_nonempty "$client_id" "client ID" || exit $?
if ! jl_validate_slug "$client_id"; then
    jl_error "Client ID must be a lowercase slug using single hyphens: $client_id"
    exit "$JL_EXIT_VALIDATION"
fi

if [ "$name_seen" -eq 0 ]; then
    client_name="$(jl_title_from_slug "$client_id")"
fi
client_name="$(jl_trim "$client_name")"
artist_name="$(jl_trim "$artist_name")"
delivery_method="$(jl_trim "$delivery_method")"
jl_assert_nonempty "$client_name" "client name" || exit $?
client_folder_name="$(jl_sanitize_folder_name "$client_name")" || exit $?

# Reject invalid explicit values before the relatively expensive workspace and
# schema validation steps. Inherited values are validated again after loading
# the studio record.
if [ "$sample_rate_seen" -eq 1 ]; then
    jl_validate_sample_rate "$sample_rate" || {
        jl_error "Unsupported sample rate: $sample_rate"
        jl_error "Supported values: 44100, 48000, 88200, 96000, 176400, 192000"
        exit "$JL_EXIT_VALIDATION"
    }
fi
if [ "$bit_depth_seen" -eq 1 ]; then
    jl_validate_bit_depth "$bit_depth" || {
        jl_error "Unsupported bit depth: $bit_depth"
        jl_error "Supported values: 16, 24, 32"
        exit "$JL_EXIT_VALIDATION"
    }
fi
if [ "$file_format_seen" -eq 1 ]; then
    file_format="$(printf '%s' "$file_format" | tr '[:lower:]' '[:upper:]')"
    jl_validate_file_format "$file_format" || {
        jl_error "Unsupported file format: $file_format"
        jl_error "Supported values: WAV, AIFF"
        exit "$JL_EXIT_VALIDATION"
    }
fi
if [ "$delivery_method_seen" -eq 1 ]; then
    jl_assert_nonempty "$delivery_method" "delivery method" || exit $?
fi
if [ "$deliverables_seen" -eq 1 ]; then
    deliverables_json="$(parse_deliverables_csv "$deliverables_csv")" || exit $?
    validate_deliverables_json "$deliverables_json" || exit $?
fi

studio_root="$(jl_context_studio_root_v11 "$PWD")" || exit $?
studio_file="$studio_root/Studio/studio.json"
clients_root="$studio_root/Clients"

jl_json_validate_local_document \
    "$studio_file" studio.schema.json mixing-studio 1.1.0 >/dev/null || exit $?
jl_metadata_validate_v11 "$studio_file" mixing-studio mutable || exit $?
jl_json_validate_unique_uuids "$studio_root" || exit $?

if ! jl_fs_is_directory_no_symlink "$clients_root"; then
    jl_error "Clients directory is missing or unsafe: $clients_root"
    exit "$JL_EXIT_CONTEXT"
fi
if [ ! -w "$clients_root" ] || [ ! -x "$clients_root" ]; then
    jl_error "Clients directory is not writable: $clients_root"
    exit "$JL_EXIT_UNSAFE"
fi
jl_fs_assert_no_symlink_components "$studio_root" "$clients_root" || exit $?

if [ "$sample_rate_seen" -eq 0 ]; then
    sample_rate="$(jl_json_get "$studio_file" '.defaults.audio.sample_rate')"
fi
if [ "$bit_depth_seen" -eq 0 ]; then
    bit_depth="$(jl_json_get "$studio_file" '.defaults.audio.bit_depth')"
fi
if [ "$file_format_seen" -eq 0 ]; then
    file_format="$(jl_json_get "$studio_file" '.defaults.audio.file_format')"
fi
if [ "$delivery_method_seen" -eq 0 ]; then
    delivery_method="$(jl_json_get "$studio_file" '.defaults.delivery.method')"
fi

jl_validate_sample_rate "$sample_rate" || {
    jl_error "Unsupported sample rate: $sample_rate"
    jl_error "Supported values: 44100, 48000, 88200, 96000, 176400, 192000"
    exit "$JL_EXIT_VALIDATION"
}
jl_validate_bit_depth "$bit_depth" || {
    jl_error "Unsupported bit depth: $bit_depth"
    jl_error "Supported values: 16, 24, 32"
    exit "$JL_EXIT_VALIDATION"
}
file_format="$(printf '%s' "$file_format" | tr '[:lower:]' '[:upper:]')"
jl_validate_file_format "$file_format" || {
    jl_error "Unsupported file format: $file_format"
    jl_error "Supported values: WAV, AIFF"
    exit "$JL_EXIT_VALIDATION"
}
jl_assert_nonempty "$delivery_method" "delivery method" || exit $?

if [ "$deliverables_seen" -eq 0 ]; then
    deliverables_json="$(jl_json_get_json "$studio_file" '.defaults.delivery.requested_deliverables')"
    validate_deliverables_json "$deliverables_json" || exit $?
fi

jl_validate_client_id_available "$studio_root" "$client_id" || exit $?
jl_fs_assert_no_case_insensitive_child_collision "$clients_root" "$client_folder_name" || exit $?

client_root="$clients_root/$client_folder_name"
if [ -e "$client_root" ] || [ -L "$client_root" ]; then
    jl_error "Client destination already exists: $client_root"
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

print_summary() {
    local heading artist_display
    heading="$1"
    artist_display="${artist_name:-<not set>}"

    printf '%s\n\n' "$heading"
    printf 'Client ID:                  %s\n' "$client_id"
    printf 'Client name:                %s\n' "$client_name"
    printf 'Client folder:              %s\n' "$client_root"
    printf 'Default artist:             %s\n' "$artist_display"
    printf 'Audio format:               %s Hz / %s-bit / %s\n' "$sample_rate" "$bit_depth" "$file_format"
    printf 'Delivery method:            %s\n' "$delivery_method"
    printf 'Requested deliverables:     %s\n' "$(printf '%s' "$deliverables_json" | jq -r 'join(", ")')"
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
  client.json
  Projects/
EOF_PLAN
    printf '\nAfter creation:\n  cd '
    shell_quote_path "$client_root"
    printf '\n  new-mix --project "PROJECT NAME"\n'
    exit 0
fi

schema_file="$(jl_json_schema_path client.schema.json)" || exit $?
# Application release provenance is independent of the v1.1 schema version.
software_version="$(jl_software_version)" || exit $?

stage_root=""
cleanup_stage() {
    local status
    status=$?
    if [ -n "$stage_root" ] && { [ -e "$stage_root" ] || [ -L "$stage_root" ]; }; then
        jl_fs_remove_entry_no_follow "$stage_root" || true
    fi
    return "$status"
}
trap cleanup_stage EXIT
trap 'exit 1' HUP INT TERM

stage_root="$(jl_txn_stage_directory_near "$client_root")" || exit $?
chmod 755 "$stage_root"
mkdir -p "$stage_root/Projects"
chmod 755 "$stage_root/Projects"

created_at="$(jl_now_iso8601)"
document_id="$(jl_uuid)" || exit $?
jl_json_assert_document_id_available "$studio_root" "$document_id" || exit $?
staged_client_file="$stage_root/client.json"

jl_template_render_json \
    "$APP_ROOT/templates/client/client.json.template" \
    "$staged_client_file" \
    DOCUMENT_ID "$document_id" \
    SOFTWARE_VERSION "$software_version" \
    CREATED_AT "$created_at" \
    CLIENT_ID "$client_id" \
    CLIENT_NAME "$client_name" \
    DEFAULT_ARTIST "$artist_name" \
    DELIVERY_METHOD "$delivery_method" || exit $?

jl_json_update "$staged_client_file" \
    '.defaults.audio.sample_rate = $sample_rate |
     .defaults.audio.bit_depth = $bit_depth |
     .defaults.audio.file_format = $file_format |
     .defaults.delivery.requested_deliverables = $deliverables' \
    --argjson sample_rate "$sample_rate" \
    --argjson bit_depth "$bit_depth" \
    --arg file_format "$file_format" \
    --argjson deliverables "$deliverables_json" || exit $?

jl_json_validate_schema "$schema_file" "$staged_client_file" >/dev/null || exit $?
jl_metadata_validate_v11 "$staged_client_file" mixing-client mutable || exit $?

jl_txn_commit_new_directory "$stage_root" "$client_root" || exit $?
stage_root=""

result_written=0
if [ "$effective_cd" -eq 1 ] && [ -n "${JL_MIXING_CD_RESULT_FILE:-}" ]; then
    write_directory_result "$JL_MIXING_CD_RESULT_FILE" "$client_root" || {
        jl_error "Client creation succeeded, but automatic directory-change setup failed."
        {
            printf 'Run:\n  cd '
            shell_quote_path "$client_root"
            printf '\n'
        } >&2
        exit "$JL_EXIT_GENERAL"
    }
    result_written=1
fi

print_summary "Client created successfully."
printf 'Configuration:               %s\n' "$client_root/client.json"

if [ "$effective_cd" -eq 1 ] && [ "$result_written" -eq 0 ]; then
    cat <<'EOF_WARNING'

Automatic directory change could not be performed because JL Mixing shell
integration is not active.
EOF_WARNING
fi

printf '\nNext:\n'
if [ "$effective_cd" -eq 0 ] || [ "$result_written" -eq 0 ]; then
    printf '  cd '
    shell_quote_path "$client_root"
    printf '\n'
fi
printf '  new-mix --project "PROJECT NAME"\n'
}
