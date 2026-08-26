from pathlib import Path
import runpy

runpy.run_path("scripts/temp_apply_160.py", run_name="__main__")

path = Path("tests/python/test_system_info.py")
text = path.read_text()
old = '            "client.files.import.execute", "client.files.import.plan", "delivery.create",\n'
new = '            "client.files.import.execute", "client.files.import.plan", "client.files.import.progress", "delivery.create",\n'
if old not in text:
    raise SystemExit("missing Python capability contract anchor")
path.write_text(text.replace(old, new, 1))

path = Path("tests/unit/test-api-system-info.sh")
text = path.read_text()
old = "'client.create','client.create.context','client.update','client.files.import.execute','client.files.import.plan',\n"
new = "'client.create','client.create.context','client.update','client.files.import.execute','client.files.import.plan','client.files.import.progress',\n"
if old not in text:
    raise SystemExit("missing shell capability contract anchor")
path.write_text(text.replace(old, new, 1))
