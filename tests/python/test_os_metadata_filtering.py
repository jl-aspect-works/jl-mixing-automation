from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from jl_mixing.audio_prep_status import build_audio_prep_status
from jl_mixing.delivery import plan_delivery
from jl_mixing.errors import ValidationError
from jl_mixing.intake import validate_intake
from jl_mixing.managed_client_files import plan_import
from jl_mixing.os_metadata import is_ignored_os_metadata_name
from jl_mixing.revision_source import build_plan as build_revision_source_plan
from jl_mixing.source_import import build_plan as build_project_source_plan


IGNORED_NAMES = (".DS_Store", "._Mix.mp3", "Thumbs.db", "desktop.ini")


def _write_source_noise(root: Path) -> None:
    for name in IGNORED_NAMES:
        (root / name).write_bytes(b"metadata")


def test_os_metadata_policy_is_platform_neutral_and_preserves_other_dotfiles() -> None:
    for name in (*IGNORED_NAMES, "THUMBS.DB", "Desktop.INI"):
        assert is_ignored_os_metadata_name(name)

    for name in (".gitignore", ".mix-notes", "DS_Store", "Thumbs.db.txt", "mix._draft.wav"):
        assert not is_ignored_os_metadata_name(name)


def test_delivery_selection_ignores_os_metadata_in_revision_root_and_variants(tmp_path: Path) -> None:
    revision = tmp_path / "Revision_01"
    delivery = tmp_path / "Delivery"
    variants = revision / "Variants"
    variants.mkdir(parents=True)
    delivery.mkdir()
    (revision / "Mix.mp3").write_bytes(b"mix")
    _write_source_noise(revision)
    (variants / "Instrumental.mp3").write_bytes(b"variant")
    (variants / "._Instrumental.mp3").write_bytes(b"metadata")

    plan = plan_delivery(
        revision,
        delivery,
        {"delivery": {"requested_deliverables": []}},
        mode="default",
        working_prefix="WORK ",
        includes=(),
        excludes=(),
        zip_name=None,
    )

    assert {record.source_path for record in plan.selected} == {"Mix.mp3", "Variants/Instrumental.mp3"}
    assert not any(record.name in IGNORED_NAMES for record in plan.excluded)


def test_intake_validation_inventory_ignores_os_metadata(tmp_path: Path) -> None:
    source = tmp_path / "intake"
    source.mkdir()
    (source / ".mix-notes").write_text("keep", encoding="utf-8")
    _write_source_noise(source)

    result = validate_intake(
        source,
        duplicate_check=False,
        ffprobe_path="",
        ffmpeg_path="",
        update_cache=False,
    )

    assert result.files_discovered == 1
    assert [record["relative_path"] for record in result.files] == [".mix-notes"]
    assert all(name not in result.report_markdown for name in IGNORED_NAMES)


def test_managed_folder_and_zip_imports_ignore_os_metadata(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "Mix.wav").write_bytes(b"mix")
    (source / ".mix-notes").write_text("keep", encoding="utf-8")
    _write_source_noise(source)

    folder_plan = plan_import(project, "folder", (source,))
    assert [record["relative_path"] for record in folder_plan["files"]] == [".mix-notes", "Mix.wav"]

    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("Mix.wav", b"mix")
        handle.writestr(".mix-notes", b"keep")
        for name in IGNORED_NAMES:
            handle.writestr(name, b"metadata")

    zip_plan = plan_import(project, "zip", (archive,))
    assert [record["relative_path"] for record in zip_plan["files"]] == [".mix-notes", "Mix.wav"]


def test_explicit_managed_metadata_only_import_is_empty(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    metadata = tmp_path / ".DS_Store"
    metadata.write_bytes(b"metadata")

    with pytest.raises(ValidationError, match="contains no files"):
        plan_import(project, "files", (metadata,))


def test_project_and_revision_source_plans_ignore_metadata_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "Mix.wav").write_bytes(b"mix")
    (source / ".mix-notes").write_text("keep", encoding="utf-8")
    _write_source_noise(source)

    project_plan = build_project_source_plan(source)
    project_files = {entry.path for entry in project_plan.entries if entry.type == "file"}
    assert project_files == {"Mix.wav", ".mix-notes"}

    revision_plan = build_revision_source_plan(source)
    assert set(revision_plan.files) == {"Mix.wav", ".mix-notes"}


def test_audio_prep_with_only_os_metadata_is_empty_not_blocked(tmp_path: Path) -> None:
    project = tmp_path / "project"
    working = project / "02_Audio_Preparation" / "Working_Audio"
    working.mkdir(parents=True)
    _write_source_noise(working)

    status = build_audio_prep_status(
        project,
        original_files=[],
        expected_sample_rate=48000,
        expected_bit_depth=24,
        expected_format="wav",
        update_cache=False,
    )

    assert status["summary"]["files_discovered"] == 0
    assert status["summary"]["blocking_errors"] == 0
    assert status["files"] == []
