"""Human-facing create-delivery command backed by the cross-platform delivery service."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .context import resolve_project
from .delivery import DeliveryCreateRequest, DeliveryCreateResult, create_delivery
from .errors import ArgumentError, JLMixingError

_USAGE = """Usage: create-delivery [options]\n\nOptions:\n  --project PATH          Explicit project directory\n  --include PATTERN       Include matching revision files; may be repeated\n  --exclude PATTERN       Exclude matching revision files; may be repeated\n  --working-prefix TEXT   Exclude files beginning with this prefix (default: WORK )\n  --overwrite             Replace a prior package with the same delivered paths\n  --clean                 Destructively replace all contents of 05_Final_Delivery\n  --zip                   Create <project-id>-rev-<NN>-<local timestamp>.zip\n  --dry-run               Show the planned package without creating it\n  -h, --help              Show this help\n"""


def _removed_option(option: str) -> ArgumentError:
    guidance = {
        "--revision": "--revision was removed in JL Mixing 1.1. create-delivery always uses state.approved_revision.",
        "--checksum": "--checksum was removed in JL Mixing 1.1. SHA-256 verification is mandatory.",
        "--mark-delivered": "--mark-delivered was removed in JL Mixing 1.1. Successful package creation records the delivered revision automatically.",
        "--non-interactive": "--non-interactive was removed in JL Mixing 1.1. create-delivery does not prompt.",
    }
    return ArgumentError(guidance[option])


def _parse(args: list[str]) -> tuple[DeliveryCreateRequest | None, bool]:
    if args in (["-h"], ["--help"]):
        return None, True
    project: Path | None = None
    includes: list[str] = []
    excludes: list[str] = []
    working_prefix = "WORK "
    overwrite = False
    clean = False
    make_zip = False
    dry_run = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-h", "--help"}:
            return None, True
        if arg in {"--revision", "--checksum", "--mark-delivered", "--non-interactive"}:
            raise _removed_option(arg)
        if arg in {"--project", "--include", "--exclude", "--working-prefix"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project":
                project = Path(value)
            elif arg == "--include":
                if not value.strip():
                    raise ArgumentError("--include cannot be empty.")
                includes.append(value)
            elif arg == "--exclude":
                if not value.strip():
                    raise ArgumentError("--exclude cannot be empty.")
                excludes.append(value)
            else:
                if value == "":
                    raise ArgumentError("--working-prefix cannot be empty.")
                working_prefix = value
        elif arg == "--overwrite":
            overwrite = True
        elif arg == "--clean":
            clean = True
        elif arg == "--zip":
            make_zip = True
        elif arg == "--dry-run":
            dry_run = True
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1

    if overwrite and clean:
        raise ArgumentError("--overwrite and --clean are mutually exclusive.")
    project_root = resolve_project(project, Path.cwd())
    return DeliveryCreateRequest(
        project_root=project_root,
        include=tuple(includes),
        exclude=tuple(excludes),
        working_prefix=working_prefix,
        overwrite=overwrite,
        clean=clean,
        make_zip=make_zip,
        dry_run=dry_run,
    ), False


def _result_payload(result: DeliveryCreateResult, *, planned: bool) -> dict[str, object]:
    return {
        "status": "planned" if planned else "success",
        "project": {
            "id": result.manifest.get("project_id", ""),
            "name": result.manifest.get("project_name", ""),
            "path": str(result.project_root),
        },
        "revision": {"number": result.approved_revision, "path": str(result.revision_root)},
        "current_revision": result.current_revision,
        "approved_revision": result.approved_revision,
        "delivered_revision": None if planned else result.approved_revision,
        "delivery_method": result.delivery_method,
        "replacement_mode": result.plan.mode,
        "zip_requested": result.zip_name is not None,
        "zip_name": result.zip_name,
        "selected": [
            {"source_name": item.name, "deliverable_type": item.deliverable_type, "path": item.path}
            for item in result.plan.selected
        ],
        "excluded": [{"name": item.name, "reason": item.reason} for item in result.plan.excluded],
        "deletions": list(result.plan.deletions),
    }


def _write_result(result: DeliveryCreateResult, *, planned: bool) -> None:
    value = os.environ.get("JL_MIXING_DELIVERY_RESULT_FILE")
    if not value:
        return
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ArgumentError(f"Delivery result file is missing or unsafe: {path}")
    path.write_text(
        json.dumps(_result_payload(result, planned=planned), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _print_plan(result: DeliveryCreateResult, *, create_zip: bool) -> None:
    print(f"Project:             {result.manifest.get('project_name', '')}")
    print(f"Current revision:    {result.current_revision}")
    print(f"Approved revision:   {result.approved_revision}")
    delivered = "null" if result.previous_delivered_revision is None else str(result.previous_delivered_revision)
    print(f"Delivered revision:  {delivered}")
    print(f"Delivery method:     {result.delivery_method}")
    print(f"Replacement mode:    {result.plan.mode}")
    print(f"Create ZIP:          {'yes' if create_zip else 'no'}")
    print("\nSelected files:")
    for item in result.plan.selected:
        print(f"  {item.name}")
        print(f"    Type: {item.deliverable_type}")
        print(f"    Destination: {item.path}")
    if result.plan.excluded:
        print("\nExcluded:")
        for item in result.plan.excluded:
            print(f"  {item.name}    {item.reason}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        request, help_only = _parse(args)
        if help_only:
            print(_USAGE, end="")
            return 0
        assert request is not None
        result = create_delivery(request)
        _write_result(result, planned=request.dry_run)

        if request.dry_run:
            print("Dry run - no changes made.\n")
            _print_plan(result, create_zip=request.make_zip)
            if request.clean:
                print(f"\nWarning: --clean will remove every existing item inside:\n  {result.delivery_root}")
                if result.plan.deletions:
                    print("\nWould delete from 05_Final_Delivery/:")
                    for item in result.plan.deletions:
                        print(f"  {item}")
            print("\nWould create:")
            for item in result.plan.selected:
                print(f"  {item.path}")
            print("  Delivery_Notes.md")
            print("  delivery-manifest.json")
            if result.zip_name is not None:
                print(f"  {result.zip_name}")
            previous = "null" if result.previous_delivered_revision is None else str(result.previous_delivered_revision)
            print("\nWould update:")
            print(f"  state.delivered_revision: {previous} -> {result.approved_revision}")
            print("  metadata.last_modified_at")
            print("\nSHA-256 verification will occur during actual package creation.")
            return 0

        print("Final delivery created successfully.\n")
        _print_plan(result, create_zip=request.make_zip)
        print(f"Files delivered:     {result.files_delivered}")
        if result.zip_name is not None:
            print(f"ZIP:                 {result.zip_name}")
        print(f"Project state:       {result.project_stage}")
        print(f"\nDelivery folder:\n  {result.delivery_root}\n\nDelivered files:")
        for item in result.plan.selected:
            print(f"  {item.path}")
        print("\nNext:")
        if result.zip_name is not None:
            print(f"  Transfer {result.zip_name} using the configured delivery method.")
        else:
            print("  Transfer the contents of 05_Final_Delivery using the configured delivery method.")
        return 0
    except JLMixingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
