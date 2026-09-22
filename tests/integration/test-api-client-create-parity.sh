#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
human="$tmp/Human Studio"
api="$tmp/API Studio"
"$ROOT/bin/new-studio" --root "$human" --name Human --engineer Jake --no-default-cd >/dev/null
"$ROOT/bin/new-studio" --root "$api" --name API --engineer Jake --no-default-cd >/dev/null
(cd "$human" && "$ROOT/bin/new-client" parity --name "Parity Client" --artist "Parity Artist" --sample-rate 48000 --bit-depth 24 --file-format WAV --delivery-method Link --deliverables main_mix,stems --no-cd >/dev/null)
(cd "$api" && "$ROOT/bin/jl-mixing" client create parity --json --name "Parity Client" --artist "Parity Artist" --sample-rate 48000 --bit-depth 24 --file-format WAV --delivery-method Link --deliverables main_mix,stems >/dev/null)
python3 - "$human/Clients/Parity Client/client.json" "$api/Clients/Parity Client/client.json" <<'PY'
import json, sys
from pathlib import Path
a=json.loads(Path(sys.argv[1]).read_text()); b=json.loads(Path(sys.argv[2]).read_text())
for d in (a,b):
    metadata=d.get("metadata", {})
    metadata.pop("document_id", None); metadata.pop("created_at", None); metadata.pop("last_modified_at", None)
assert a == b
PY
pass "API and human commands create equivalent authoritative state"
echo "[OK] Automation API client.create parity ($TEST_COUNT assertions)"
