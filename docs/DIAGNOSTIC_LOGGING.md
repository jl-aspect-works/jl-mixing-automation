# Diagnostic Logging

JL Mixing Automation writes structured JSON Lines diagnostics to a per-user log file. Logging is best-effort and never changes stdout/stderr API or progress contracts.

## Default locations

- macOS: `~/Library/Logs/JL Mixing/automation.jsonl`
- Windows: `%LOCALAPPDATA%\JL Mixing\logs\automation.jsonl`
- Linux: `$XDG_STATE_HOME/jl-mixing/logs/automation.jsonl` or `~/.local/state/jl-mixing/logs/automation.jsonl`

Set `JL_MIXING_LOG_DIR` to override the directory. Set `JL_MIXING_LOG_LEVEL=debug` for detailed progress events; the default level is `info`.

## Retention

The active file rotates at 5 MB. One rotated backup is retained as `automation.jsonl.1`, bounding normal disk use to roughly 10 MB.

## Privacy and support

Logs contain operation names, timing/count information, status/error diagnostics, and at debug level progress event metadata such as active file names. They do not intentionally log file contents, metadata-document contents, credentials, secrets, or secret command-line values. Known sensitive field names are redacted by the logger.

When troubleshooting, reproduce the issue once with `JL_MIXING_LOG_LEVEL=debug`, then collect `automation.jsonl` and, when present, `automation.jsonl.1`.