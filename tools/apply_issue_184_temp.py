from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


p = Path("src/jl_mixing/managed_client_files.py")
s = p.read_text()
s = replace_once(
    s,
    '''def _item(project_root: Path, item_id: str, area: str, relative: str, source: SourceFile, *, depends_on: str | None = None) -> dict[str, Any]:
    destination = _managed_destination(project_root, relative)
    state = _file_state(destination)
''',
    '''def _plan_file_state(project_root: Path, relative: str, validated_parents: set[Path]) -> str:
    """Inspect a planned destination with one metadata call per unique parent/file."""
    safe = _safe_relative(relative)
    destination = project_root / Path(safe)
    current = project_root
    for part in Path(safe).parts[:-1]:
        current = current / part
        if current in validated_parents:
            continue
        try:
            info = current.stat(follow_symlinks=False)
        except FileNotFoundError:
            validated_parents.add(current)
            continue
        if stat.S_ISLNK(info.st_mode):
            raise UnsafeOperationError(f"Managed destination traverses a symlink: {current}")
        if not stat.S_ISDIR(info.st_mode):
            raise UnsafeOperationError(f"Managed destination parent is not a directory: {current}")
        validated_parents.add(current)
    try:
        info = destination.stat(follow_symlinks=False)
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise UnsafeOperationError(f"Managed destination is not a regular file: {destination}")
    return f"file:{info.st_size}:{info.st_mtime_ns}"


def _item(
    project_root: Path,
    item_id: str,
    area: str,
    relative: str,
    source: SourceFile,
    *,
    depends_on: str | None = None,
    validated_parents: set[Path] | None = None,
) -> dict[str, Any]:
    state = (
        _plan_file_state(project_root, relative, validated_parents)
        if validated_parents is not None
        else _file_state(_managed_destination(project_root, relative))
    )
''',
    "optimized file-state helper",
)
s = replace_once(
    s,
    "def plan_import(project_root: Path, source_kind: str, sources: tuple[Path, ...]) -> dict[str, Any]:\n",
    "def plan_import(\n    project_root: Path,\n    source_kind: str,\n    sources: tuple[Path, ...],\n    *,\n    progress: ProgressCallback | None = None,\n) -> dict[str, Any]:\n",
    "base plan signature",
)
s = replace_once(
    s,
    '''    items_started = time.perf_counter()
    items: list[dict[str, Any]] = []
    for index, source in enumerate(files):
        original_rel = (ORIGINAL_ROOT / Path(source.relative_path)).as_posix()
        audio_rel = (AUDIO_ROOT / Path(source.relative_path)).as_posix()
        original_id = f"original:{index}"
        items.append(_item(project_root, original_id, "original_delivery", original_rel, source))
        items.append(_item(project_root, f"audio:{index}", "audio_prep", audio_rel, source, depends_on=original_id))
''',
    '''    items_started = time.perf_counter()
    items: list[dict[str, Any]] = []
    validated_parents: set[Path] = set()
    total_files = len(files)
    for index, source in enumerate(files):
        original_rel = (ORIGINAL_ROOT / Path(source.relative_path)).as_posix()
        audio_rel = (AUDIO_ROOT / Path(source.relative_path)).as_posix()
        original_id = f"original:{index}"
        items.append(_item(project_root, original_id, "original_delivery", original_rel, source, validated_parents=validated_parents))
        items.append(_item(project_root, f"audio:{index}", "audio_prep", audio_rel, source, depends_on=original_id, validated_parents=validated_parents))
        if progress is not None:
            progress({"phase": "planning", "completed": index + 1, "total": total_files, "active": [source.relative_path]})
''',
    "base plan loop",
)
p.write_text(s)

p = Path("src/jl_mixing/managed_client_file_provenance.py")
s = p.read_text()
s = replace_once(
    s,
    '''def plan_import(project_root: Path, source_kind: str, sources: tuple[Path, ...]) -> dict[str, Any]:
    total_started = time.perf_counter()
    base_started = time.perf_counter()
    plan = base.plan_import(project_root, source_kind, sources)
''',
    '''def plan_import(
    project_root: Path,
    source_kind: str,
    sources: tuple[Path, ...],
    *,
    progress: base.ProgressCallback | None = None,
) -> dict[str, Any]:
    total_started = time.perf_counter()
    base_started = time.perf_counter()
    base_progress = None
    if progress is not None:
        def base_progress(event: dict[str, Any]) -> None:
            completed = int(event.get("completed", 0))
            total = int(event.get("total", 0))
            progress({**event, "completed": completed, "total": total * 2})
    plan = base.plan_import(project_root, source_kind, sources, progress=base_progress)
''',
    "provenance plan signature",
)
s = replace_once(
    s,
    '''    working_index = _WorkingHashIndex(project_root)
    items: list[dict[str, Any]] = []
    for item in plan["items"]:
''',
    '''    working_index = _WorkingHashIndex(project_root)
    items: list[dict[str, Any]] = []
    resolved_count = 0
    total_sources = len(source_objects)
    for item in plan["items"]:
''',
    "provenance resolution setup",
)
s = replace_once(
    s,
    '''        if destination:
            items.append(base._item(project_root, item["id"], "audio_prep", destination, source, depends_on=item.get("depends_on")))
        else:
            items.append(item)
''',
    '''        if destination:
            items.append(base._item(project_root, item["id"], "audio_prep", destination, source, depends_on=item.get("depends_on")))
        else:
            items.append(item)
        resolved_count += 1
        if progress is not None:
            progress({"phase": "planning", "completed": total_sources + resolved_count, "total": total_sources * 2, "active": [source_relative]})
''',
    "provenance resolution progress",
)
s = replace_once(
    s,
    '''    content_hashes: dict[str, str] | None = None,
) -> None:
''',
    '''    content_hashes: dict[str, str] | None = None,
    *,
    progress: base.ProgressCallback | None = None,
) -> None:
''',
    "finalize signature",
)
s = replace_once(
    s,
    '''    recorded_count = 0
    for item in plan["items"]:
        if item["area"] != "audio_prep" or statuses.get(item["id"]) not in {"created", "replaced"}:
            continue
        source_relative = base._safe_relative(item["source_relative_path"])
        working_relative = base._safe_relative(item["destination_relative_path"])
        source_path = base._managed_destination(project_root, (base.ORIGINAL_ROOT / Path(source_relative)).as_posix())
        working_path = base._managed_destination(project_root, working_relative)
        if not source_path.is_file() or not working_path.is_file():
            continue
        source_size = source_path.stat().st_size
        working_size = working_path.stat().st_size
        reusable_hash = content_hashes.get(source_relative) if content_hashes is not None else None
        if reusable_hash:
''',
    '''    recorded_count = 0
    eligible_items = [item for item in plan["items"] if item["area"] == "audio_prep" and statuses.get(item["id"]) in {"created", "replaced"}]
    total_eligible = len(eligible_items)
    for item in eligible_items:
        source_relative = base._safe_relative(item["source_relative_path"])
        working_relative = base._safe_relative(item["destination_relative_path"])
        reusable_hash = content_hashes.get(source_relative) if content_hashes is not None else None
        if reusable_hash:
            source_size = int(item["size_bytes"])
            working_size = source_size
        else:
            source_path = base._managed_destination(project_root, (base.ORIGINAL_ROOT / Path(source_relative)).as_posix())
            working_path = base._managed_destination(project_root, working_relative)
            if not source_path.is_file() or not working_path.is_file():
                continue
            source_size = source_path.stat().st_size
            working_size = working_path.stat().st_size
        if reusable_hash:
''',
    "finalize loop",
)
s = replace_once(
    s,
    "        recorded_count += 1\n        changed = True\n",
    "        recorded_count += 1\n        changed = True\n        if progress is not None:\n            progress({\"phase\": \"finalizing\", \"completed\": recorded_count, \"total\": total_eligible, \"active\": [source_relative]})\n",
    "finalize progress",
)
s = replace_once(
    s,
    '''    result = base.execute_plan(project_root, plan, decisions, progress=progress, content_hashes=content_hashes)
    base_execute_ms = _elapsed_ms(base_started)
    lineage_started = time.perf_counter()
    _record_successful_lineage(project_root, plan, result, content_hashes)
    lineage_ms = _elapsed_ms(lineage_started)
''',
    '''    def base_progress(event: dict[str, Any]) -> None:
        if progress is not None and event.get("phase") != "complete":
            progress(event)

    result = base.execute_plan(project_root, plan, decisions, progress=base_progress if progress is not None else None, content_hashes=content_hashes)
    base_execute_ms = _elapsed_ms(base_started)
    lineage_started = time.perf_counter()
    _record_successful_lineage(project_root, plan, result, content_hashes, progress=progress)
    lineage_ms = _elapsed_ms(lineage_started)
    if progress is not None:
        total_files = len(plan.get("files", []))
        progress({"phase": "complete", "completed": total_files, "total": total_files, "active": []})
''',
    "execute progress wrapper",
)
p.write_text(s)

p = Path("src/jl_mixing/api/managed_client_files.py")
s = p.read_text()
s = replace_once(s, "        self.overall_total = total_files * 2 + 1\n", "        self.overall_total = total_files * 3\n", "overall total")
s = replace_once(
    s,
    '''        if phase == "complete":
            self._finish_staging()
            self._emit("finalizing", self.total_files, [], self.total_files * 2)
            self.finalizing_emitted = True
            return
''',
    '''        if phase == "finalizing":
            self._finish_staging()
            self._emit("finalizing", completed, active, self.total_files * 2 + completed)
            self.finalizing_emitted = completed >= self.total_files
            return

        if phase == "complete":
            self._finish_staging()
            return
''',
    "adapter finalizing phase",
)
s = replace_once(
    s,
    '''    def finish(self) -> None:
        self._finish_staging()
        if not self.finalizing_emitted:
            self._emit("finalizing", self.total_files, [], self.total_files * 2)
            self.finalizing_emitted = True
        self._emit("complete", self.total_files, [], self.overall_total)
''',
    '''    def finish(self) -> None:
        self._finish_staging()
        if not self.finalizing_emitted:
            self._emit("finalizing", 0, [], self.total_files * 2)
        self._emit("complete", self.total_files, [], self.overall_total)
''',
    "adapter finish",
)
s = replace_once(
    s,
    "        plan = plan_import(root, request.source_kind, request.sources)\n",
    "        progress_enabled = request.progress == _PROGRESS_MODE\n        plan = plan_import(root, request.source_kind, request.sources, progress=(lambda event: _emit_progress(operation, {**event, \"overall_completed\": event.get(\"completed\"), \"overall_total\": event.get(\"total\")})) if progress_enabled else None)\n",
    "plan progress call",
)
s = replace_once(
    s,
    "        full_plan = plan_import(root, request.source_kind, request.sources)\n",
    "        full_plan = plan_import(root, request.source_kind, request.sources, progress=(lambda event: _emit_progress(operation, {**event, \"overall_completed\": event.get(\"completed\"), \"overall_total\": event.get(\"total\")})) if progress_enabled else None)\n",
    "replan progress call",
)
s = replace_once(s, "            if not execute:\n                raise ArgumentError(\"import-plan does not accept --progress.\")\n", "", "plan progress parser")
s = replace_once(s, "                raise ArgumentError(\"import-execute accepts at most one --progress option.\")\n", "                raise ArgumentError(\"managed import accepts at most one --progress option.\")\n", "progress duplicate message")
p.write_text(s)
