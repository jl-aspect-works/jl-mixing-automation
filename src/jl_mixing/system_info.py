"""Automation API 1.0 discovery document."""

from __future__ import annotations

from .versions import api_version, application_version, schema_root

_CAPABILITIES = [
    "audio.prep.provenance.sha256",
    "audio.prep.reset.execute",
    "audio.prep.reset.plan",
    "audio.prep.validation.structured",
    "client.create",
    "client.create.context",
    "client.update",
    "client.files.import.execute",
    "client.files.import.plan",
    "client.files.import.progress",
    "delivery.create",
    "delivery.package.delete",
    "delivery.package.rebuild",
    "delivery.status",
    "intake.validate",
    "intake.validate.incremental",
    "intake.validate.progress",
    "intake.validate.report",
    "intake.validate.structured",
    "managed.requests.stdinjson",
    "project.create",
    "project.create.artist",
    "project.update",
    "revision.approve",
    "revision.close",
    "revision.create",
    "revision.create.description",
    "revision.reopen",
    "revision.unapprove",
    "revision.update.description",
    "studio.update",
    "system.info",
]


def document() -> dict[str, object]:
    version = api_version()
    return {
        "api_version": version,
        "application": {"name": "jl-mixing", "version": application_version()},
        "metadata": {
            "readable_schema_versions": ["1.1.0"],
            "writable_schema_version": "1.1.0",
        },
        "capabilities": list(_CAPABILITIES),
        "schemas": {
            "installed_path": str(schema_root().resolve()),
            "public_base_url": f"https://jlaudio.github.io/jl-mixing/api/v{version}/schemas/",
        },
    }
