#!/bin/bash
# Stops a push that would publish a secret: the real values of .env (API key, connector secret, ...), a connector URL,
# or a forbidden file type, in the tracked files or anywhere in the git history. Run it by hand or let the pre-push hook run it.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
"$PY" - <<'PYEOF'
import re, subprocess, sys
from pathlib import Path

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True).stdout

problems = []
tracked = git("ls-files").splitlines()
bad_names = re.compile(r"(^|/)\.env($|\.(?!example$))|\.(pem|key|p12|mp3|wav|m4a|mp4|mov|zip)$|transcript", re.I)
problems += [f"forbidden file is tracked: {f}" for f in tracked if bad_names.search(f)]

tree = "\n".join(Path(f).read_text(errors="ignore") for f in tracked if Path(f).is_file())
history = git("log", "-p", "--all", "--no-color")
secrets = {}
if Path(".env").exists():
    for line in Path(".env").read_text().splitlines():
        line = line.strip().lstrip("# ").strip()
        if "=" in line and not line.startswith("ALLOWED"):
            k, v = line.split("=", 1)
            v = v.strip().strip("\"'")
            if len(v) >= 8 and v.lower() not in ("true", "false") and not v.startswith(("http", "127.0.0.1", "localhost")) and re.search(r"KEY|SECRET|TOKEN|PASS", k, re.I):
                secrets[k] = v
for k, v in secrets.items():
    if v in tree:
        problems.append(f"the value of {k} from .env is in a tracked file")
    if v in history:
        problems.append(f"the value of {k} from .env is in the git history")
pattern = re.compile(r"trycloudflare\.com/mcp/[A-Za-z0-9_-]{20,}|x-api-key['\"]?\s*[:=]\s*['\"][0-9a-f-]{36}|[?&]key=[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
for where, text in (("a tracked file", tree), ("the git history", history)):
    hit = pattern.search(text)
    if hit:
        problems.append(f"a connector URL or API key pattern is in {where}: {hit.group(0)[:24]}...")
print(f"checked {len(tracked)} tracked files, the whole history and {len(secrets)} secrets from .env")
if problems:
    print("DO NOT PUSH:")
    for p in problems:
        print(" -", p)
    sys.exit(1)
print("OK: no secret, connector URL or forbidden file found.")
PYEOF
