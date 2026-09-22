"""Human-facing approve-mix command backed by the cross-platform approval service."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .approval import RevisionApproveRequest, approve_revision, derive_project_stage
from .context import resolve_project
from .errors import ArgumentError, JLMixingError, ValidationError

_USAGE = """Usage: approve-mix [options]\n\nOptions:\n  --project PATH       Explicit project directory\n  --revision NUMBER    Revision to approve (default: current revision)\n  --approved-by NAME   Approver identity (default: Client)\n  --date TIMESTAMP     ISO-8601 approval timestamp (default: current time)\n  --dry-run            Show the approval change without modifying the project\n  -h, --help           Show this help\n"""


def _parse(args: list[str]) -> tuple[RevisionApproveRequest | None, bool]:
    if args in (["-h"], ["--help"]):
        return None, True
    project: Path | None = None
    revision: int | None = None
    approved_by = "Client"
    approved_at: str | None = None
    dry_run = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--notes":
            raise ArgumentError(
                "--notes was removed in JL Mixing 1.1.\n"
                "Revision_Notes.md is user-managed and is not changed by approve-mix."
            )
        if arg == "--non-interactive":
            raise ArgumentError(
                "--non-interactive was removed in JL Mixing 1.1.\n"
                "approve-mix already uses supplied values and defaults without prompting."
            )
        if arg in {"-h", "--help"}:
            return None, True
        if arg == "--dry-run":
            dry_run = True
        elif arg in {"--project", "--revision", "--approved-by", "--date"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project":
                project = Path(value)
            elif arg == "--revision":
                try:
                    revision = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Revision number must be a positive integer: {value}") from exc
            elif arg == "--approved-by":
                approved_by = value
            else:
                approved_at = value
        else:
            raise ArgumentError(f"Unknown option: {arg}")
        index += 1

    project_root = resolve_project(project, Path.cwd())
    return RevisionApproveRequest(
        project_root=project_root,
        revision=revision,
        approved_by=approved_by,
        approved_at=approved_at,
        dry_run=dry_run,
    ), False


def _load_before(project_root: Path) -> dict[str, object]:
    path = project_root / "00_Admin" / "project-manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        request, help_only = _parse(args)
        if help_only:
            print(_USAGE, end="")
            return 0
        assert request is not None
        before = _load_before(request.project_root)
        state = before["state"]
        current = state["current_revision"]
        selected = current if request.revision is None else request.revision
        prior_record = next(
            (record for record in before.get("revisions", []) if record.get("number") == selected),
            None,
        )
        prior_approved_at = None
        if isinstance(prior_record, dict) and isinstance(prior_record.get("approval"), dict):
            prior_approved_at = prior_record["approval"].get("approved_at")

        try:
            result = approve_revision(request)
        except ValidationError as exc:
            if "already the approved revision" in str(exc):
                print(f"Error: {exc}", file=sys.stderr)
                print("No changes made.\n\nNext:\n  create-delivery")
                return exc.exit_code
            raise

        if request.dry_run:
            print("Dry run — no changes made.\n")
            print(f"Project:                     {result.manifest['project_name']}")
            print(f"Current revision:            {result.current_revision}")
            print(f"Selected revision:           {result.number}")
            current_approved = "<none>" if result.previous_approved_revision is None else str(result.previous_approved_revision)
            print(f"Current approved revision:   {current_approved}")
            print(f"Approver:                    {result.approved_by}")
            if request.approved_at is not None:
                print(f"Approval timestamp:          {request.approved_at.strip()}")
            else:
                print("Approval timestamp:          current time at execution")
            print("\nWould update:")
            prior_pointer = "null" if result.previous_approved_revision is None else str(result.previous_approved_revision)
            arrow = "->" if os.name == "nt" else "→"
            print(f"  state.approved_revision: {prior_pointer} {arrow} {result.number}")
            print(f"  Revision {result.number} approval metadata")
            print("  metadata.last_modified_at")
            if prior_approved_at is not None:
                print(
                    f"\nRevision {result.number} was approved previously; "
                    "its prior approval metadata would be replaced."
                )
            print("\nWould not change:")
            print(f"  state.current_revision: {result.current_revision}")
            delivered = "null" if result.delivered_revision is None else str(result.delivered_revision)
            print(f"  state.delivered_revision: {delivered}")
            print("  Revision files")
            print("  Final delivery package")
            return 0

        print("Revision approved successfully.\n")
        print(f"Project:                     {result.manifest['project_name']}")
        print(f"Approved revision:           {result.number}")
        if result.number != result.current_revision:
            print(f"Current revision:            {result.current_revision}")
        print(f"Approved by:                 {result.approved_by}")
        print(f"Approved at:                 {result.approved_at}")
        print(f"Project state:               {derive_project_stage(result.manifest)}")
        if result.number != result.current_revision:
            print("\nThe approved revision is older than the current working revision.")
        if result.delivered_revision is not None and result.delivered_revision != result.number:
            print(f"\nCurrent final delivery represents Revision {result.delivered_revision}.")
            print("Running create-delivery will require explicit replacement authorization.")
        print("\nNext:\n  create-delivery")
        return 0
    except JLMixingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
