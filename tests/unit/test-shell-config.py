#!/usr/bin/env python3
"""Unit tests for byte-preserving managed shell configuration."""
from pathlib import Path
import importlib.util
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "manage_shell_config", ROOT / "tools" / "manage-shell-config.py"
)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

count = 0

def check(condition: bool, label: str) -> None:
    global count
    if not condition:
        raise AssertionError(label)
    count += 1
    print(f"[PASS] {label}")

block = (
    module.BEGIN
    + b"\nexport PATH='/tmp/bin':\"$PATH\"\n"
    + module.END
    + b"\n"
)
original = b"# user prefix\r\nexport USER_SETTING=1\n"
installed = module.install_block(original, block)
check(installed.startswith(original), "install preserves existing bytes")
check(module.locate_block(installed) is not None, "installed block is discoverable")
reinstalled = module.install_block(installed, block.replace(b"/tmp/bin", b"/new/bin"))
check(reinstalled.count(module.BEGIN) == 1, "reinstall replaces instead of duplicating")
check(b"/new/bin" in reinstalled and b"/tmp/bin" not in reinstalled, "reinstall updates block")
removed = module.remove_block(reinstalled, require_present=True)
check(removed == original, "remove restores exact outside bytes")
check(module.remove_block(b"", require_present=False) == b"", "optional remove accepts absent block")

bad_documents = [
    module.BEGIN + b"\n",
    module.END + b"\n",
    module.END + b"\n" + module.BEGIN + b"\n",
    module.BEGIN + b"\n" + module.BEGIN + b"\n" + module.END + b"\n",
    b"prefix " + module.BEGIN + b"\n" + module.END + b"\n",
]
for index, data in enumerate(bad_documents, 1):
    try:
        module.locate_block(data)
    except module.MarkerError:
        check(True, f"malformed marker case {index} rejected")
    else:
        check(False, f"malformed marker case {index} rejected")

with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / ".zshrc"
    path.write_bytes(original)
    module.atomic_write(path, installed)
    check(path.read_bytes() == installed, "atomic write stores managed content")

print(f"[OK] manage-shell-config.py ({count} assertions)")
