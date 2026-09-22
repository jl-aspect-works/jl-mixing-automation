# Automation API Implementation Status

## Current implementation

JL Mixing Automation v1.5 implements Automation API `1.0` on the same Python
services used by the human CLI. Discovery is available through:

```text
jl-mixing system-info --json
```

The discovery response reports independently versioned contracts:

- Automation API version from `API_VERSION`
- Automation application release from `VERSION`
- readable and writable workspace metadata schema versions
- implemented machine-facing capabilities
- installed/public API schema locations

Workspace metadata remains schema `1.1.0`; application release changes do not
implicitly change API or metadata-schema versions.

## Advertised capability set

v1.5 advertises:

```text
client.create
client.delete.plan
client.delete.execute
delivery.create
intake.validate
intake.validate.report
project.create
project.create.artist
project.delete.plan
project.delete.execute
revision.approve
revision.create
revision.create.description
system.info
```

Each advertised workflow capability is backed by the shared Python service layer
and structured API adapter rather than by parsing human-readable CLI output.

## Contract artifacts

API 1.0 schemas are shipped beneath:

```text
api/schemas/v1.0/
```

Reviewed success/error examples are shipped beneath:

```text
api/examples/v1.0/
```

`system-info` reports the installed schema location so offline clients can
validate provider responses against the exact installed contract.

## Distribution contract

Windows and macOS release packages include the dispatcher, `API_VERSION`, API
schemas/examples, shared Python services, and private runtime as one application
unit. Linux/source installation uses the compatibility installer but exposes the
same API contract.

Release and lifecycle tests verify provider discovery, installed schemas,
application/API/schema version separation, and workspace preservation during
install/uninstall operations.

## Compatibility rule

Clients must admit providers based on:

1. compatible `api_version`
2. required capability names
3. supported readable/writable metadata schema versions as appropriate

Clients must not require the Automation product release number to match their
own release number. Within API major version 1, clients should tolerate unknown
optional response fields and rely on capability discovery for feature admission.

## Human CLI relationship

Human commands and machine operations share authoritative workflow services, but
their presentation contracts are separate. Human-formatted stdout/stderr must
not be treated as Automation API JSON unless a documented machine operation
explicitly defines that output.
