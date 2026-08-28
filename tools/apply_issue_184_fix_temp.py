from pathlib import Path

p = Path("src/jl_mixing/api/managed_client_files.py")
s = p.read_text()
old = '            self._emit("finalizing", completed, active, self.total_files * 2 + completed)\n'
new = '            overall_completed = min(self.total_files * 2 + completed, self.overall_total - 1)\n            self._emit("finalizing", completed, active, overall_completed)\n'
if old not in s:
    raise SystemExit("finalizing progress anchor missing")
p.write_text(s.replace(old, new, 1))
