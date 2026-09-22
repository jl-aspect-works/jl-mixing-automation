"""Reconcile managed delivery status against current project delivery settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def reconcile_delivery_requirements(project: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Mark existing delivery state stale when authoritative delivery settings differ.

    Requested deliverables are intentionally not inferred from filenames. They are
    a human checklist/reference because mix engineers are free to use arbitrary
    filenames for their delivery variants. Delivery status therefore reconciles
    only settings Automation can determine authoritatively.
    """
    project_path = project / "00_Admin" / "project-manifest.json"
    delivery_path = project / "05_Final_Delivery" / "delivery-manifest.json"
    if not delivery_path.is_file() or delivery_path.is_symlink():
        return data
    try:
        project_doc = json.loads(project_path.read_text(encoding="utf-8"))
        delivery_doc = json.loads(delivery_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return data
    project_delivery = project_doc.get("delivery") if isinstance(project_doc, dict) else None
    built_delivery = delivery_doc.get("delivery") if isinstance(delivery_doc, dict) else None
    if not isinstance(project_delivery, dict) or not isinstance(built_delivery, dict):
        return data

    expected_method = project_delivery.get("method")
    built_method = built_delivery.get("method")
    if expected_method == built_method:
        return data

    issues = data.setdefault("issues", [])
    issues.append({
        "code": "DELIVERY_METHOD_CHANGED",
        "message": "Project delivery method changed after the managed delivery was built.",
    })
    data["state"] = "needs_attention"
    if data.get("package_state") == "current":
        data["package_state"] = "stale"
        data["current_package"] = None
    return data
