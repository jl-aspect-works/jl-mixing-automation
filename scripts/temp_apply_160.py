from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:80]!r}")
    file.write_text(text.replace(old, new, 1))


path = "src/jl_mixing/api/managed_client_files.py"
replace(path, "import json\nfrom dataclasses import dataclass", "import json\nimport sys\nfrom dataclasses import dataclass")
replace(path, "from ..versions import api_version\n", "from ..versions import api_version\n\n_PROGRESS_PREFIX = \"JL_PROGRESS \"\n_PROGRESS_MODE = \"stderr-json\"\n")
replace(path, "    selected_relative_paths: tuple[str, ...] | None = None\n", "    selected_relative_paths: tuple[str, ...] | None = None\n    progress: str | None = None\n")
replace(path, "def _project_data(root: Path) -> dict[str, str]:\n    return {\"path\": str(root), \"workspace_path\": str(studio_root(root))}\n", "def _project_data(root: Path) -> dict[str, str]:\n    return {\"path\": str(root), \"workspace_path\": str(studio_root(root))}\n\n\ndef _emit_progress(operation: str, event: dict[str, Any]) -> None:\n    print(\n        _PROGRESS_PREFIX + json.dumps({\"operation\": operation, **event}, separators=(\",\", \":\"), sort_keys=True),\n        file=sys.stderr,\n        flush=True,\n    )\n")
replace(path, "        result = execute_plan(root, plan, request.decisions or {})\n", "        progress_callback = (lambda event: _emit_progress(operation, event)) if request.progress == _PROGRESS_MODE else None\n        result = execute_plan(root, plan, request.decisions or {}, progress=progress_callback)\n")
replace(path, "    plan_id: str | None = None; decisions: dict[str, str] | None = None; selected_relative_paths: list[str] = []\n", "    plan_id: str | None = None; decisions: dict[str, str] | None = None; selected_relative_paths: list[str] = []; progress: str | None = None\n")
replace(path, "        if arg == \"--json\": json_seen += 1\n        elif arg in {\"--project\", \"--source-kind\", \"--source\", \"--plan-id\", \"--decisions-json\", \"--include-relative-path\"}:", "        if arg == \"--json\": json_seen += 1\n        elif arg.startswith(\"--progress=\"):\n            value = arg.split(\"=\", 1)[1]\n            if not execute:\n                raise ArgumentError(\"import-plan does not accept --progress.\")\n            if value != _PROGRESS_MODE:\n                raise ArgumentError(f\"Unsupported managed import progress mode: {value}. Expected {_PROGRESS_MODE}.\")\n            if progress is not None:\n                raise ArgumentError(\"import-execute accepts at most one --progress option.\")\n            progress = value\n        elif arg in {\"--project\", \"--source-kind\", \"--source\", \"--plan-id\", \"--decisions-json\", \"--include-relative-path\"}:")
replace(path, "    return ImportRequest(project, source_kind, tuple(sources), plan_id, decisions, tuple(selected_relative_paths) if selected_relative_paths else None)\n", "    return ImportRequest(project, source_kind, tuple(sources), plan_id, decisions, tuple(selected_relative_paths) if selected_relative_paths else None, progress)\n")

path = "src/jl_mixing/managed_client_files.py"
replace(path, "from typing import Any, Iterable\n", "from typing import Any, Callable, Iterable\n")
replace(path, "AUDIO_CACHE = Path(\"00_Admin\") / \"audio-prep-validation-cache.json\"\n", "AUDIO_CACHE = Path(\"00_Admin\") / \"audio-prep-validation-cache.json\"\nProgressCallback = Callable[[dict[str, Any]], None]\n")
replace(path, "def execute_plan(project_root: Path, plan: dict[str, Any], decisions: dict[str, str]) -> dict[str, Any]:\n", "def execute_plan(\n    project_root: Path,\n    plan: dict[str, Any],\n    decisions: dict[str, str],\n    *,\n    progress: ProgressCallback | None = None,\n) -> dict[str, Any]:\n")
replace(path, "    transaction = create_staging_directory(project_root / \"00_Admin\", \".jl-managed-import-\")\n", "    total_files = len(source_objects)\n    completed_files = 0\n    remaining_by_source = {relative: sum(1 for item in plan[\"items\"] if item[\"source_relative_path\"] == relative) for relative in source_objects}\n\n    def emit_progress(phase: str, active: list[str]) -> None:\n        if progress is not None:\n            progress({\"phase\": phase, \"completed\": completed_files, \"total\": total_files, \"active\": active})\n\n    def complete_item(item: dict[str, Any]) -> None:\n        nonlocal completed_files\n        relative = item[\"source_relative_path\"]\n        remaining_by_source[relative] -= 1\n        if remaining_by_source[relative] == 0:\n            completed_files += 1\n        emit_progress(\"importing\", [relative] if remaining_by_source[relative] else [])\n\n    transaction = create_staging_directory(project_root / \"00_Admin\", \".jl-managed-import-\")\n")
replace(path, "        staged = {relative: _stage_source(source, stage) for relative, source in source_objects.items()}\n", "        staged: dict[str, Path] = {}\n        for relative, source in source_objects.items():\n            emit_progress(\"staging\", [relative])\n            staged[relative] = _stage_source(source, stage)\n        emit_progress(\"importing\", [])\n")
replace(path, "        for position, item in enumerate(plan[\"items\"]):\n            dependency = item.get(\"depends_on\")\n", "        for position, item in enumerate(plan[\"items\"]):\n            relative = item[\"source_relative_path\"]\n            emit_progress(\"importing\", [relative])\n            dependency = item.get(\"depends_on\")\n")
replace(path, "                results.append({\"id\": item[\"id\"], \"result\": \"skipped\"})\n                continue\n            if item[\"conflict\"] and decisions.get(item[\"id\"]) == \"skip\":\n                results.append({\"id\": item[\"id\"], \"result\": \"skipped\"})\n                continue\n", "                results.append({\"id\": item[\"id\"], \"result\": \"skipped\"})\n                complete_item(item)\n                continue\n            if item[\"conflict\"] and decisions.get(item[\"id\"]) == \"skip\":\n                results.append({\"id\": item[\"id\"], \"result\": \"skipped\"})\n                complete_item(item)\n                continue\n")
replace(path, "            results.append({\"id\": item[\"id\"], \"result\": \"replaced\" if backup else \"created\"})\n        invalidated = _invalidate(project_root, changed_original, changed_audio)\n        return {\"items\": results, \"invalidations\": invalidated}\n", "            results.append({\"id\": item[\"id\"], \"result\": \"replaced\" if backup else \"created\"})\n            complete_item(item)\n        invalidated = _invalidate(project_root, changed_original, changed_audio)\n        emit_progress(\"complete\", [])\n        return {\"items\": results, \"invalidations\": invalidated}\n")

path = "src/jl_mixing/managed_client_file_provenance.py"
replace(path, "def execute_plan(project_root: Path, plan: dict[str, Any], decisions: dict[str, str]) -> dict[str, Any]:\n    result = base.execute_plan(project_root, plan, decisions)\n", "def execute_plan(\n    project_root: Path,\n    plan: dict[str, Any],\n    decisions: dict[str, str],\n    *,\n    progress: base.ProgressCallback | None = None,\n) -> dict[str, Any]:\n    result = base.execute_plan(project_root, plan, decisions, progress=progress)\n")

path = "src/jl_mixing/system_info.py"
replace(path, "    \"client.files.import.execute\",\n    \"client.files.import.plan\",\n", "    \"client.files.import.execute\",\n    \"client.files.import.plan\",\n    \"client.files.import.progress\",\n")

path = "tests/python/test_managed_client_files_api.py"
p = Path(path)
text = p.read_text()
anchor = "    def test_discovery_advertises_managed_capabilities(self):\n"
test = '''    def test_import_execute_progress_is_opt_in_and_preserves_stdout_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = fixture(root / "studio")
            source = root / "delivery"
            source.mkdir()
            (source / "one.wav").write_bytes(b"one")
            (source / "two.wav").write_bytes(b"two")
            planned = run(project, "client-files", "import-plan", "--json", "--source-kind", "folder", "--source", str(source))
            plan = json.loads(planned.stdout)["data"]["plan"]
            executed = run(project, "client-files", "import-execute", "--json", "--source-kind", "folder", "--source", str(source), "--plan-id", plan["plan_id"], "--progress=stderr-json")
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            payload = json.loads(executed.stdout)
            self.assertEqual(payload["operation"], "client.files.import.execute")
            lines = [line for line in executed.stderr.splitlines() if line.startswith("JL_PROGRESS ")]
            self.assertGreaterEqual(len(lines), 3)
            events = [json.loads(line.removeprefix("JL_PROGRESS ")) for line in lines]
            self.assertTrue(all(event["operation"] == "client.files.import.execute" for event in events))
            self.assertEqual(events[-1]["phase"], "complete")
            self.assertEqual(events[-1]["completed"], 2)
            self.assertEqual(events[-1]["total"], 2)

'''
if test not in text:
    if anchor not in text:
        raise SystemExit("missing managed API test anchor")
    p.write_text(text.replace(anchor, test + anchor, 1))
