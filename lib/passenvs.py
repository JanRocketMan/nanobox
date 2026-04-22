#!/usr/bin/env python3
"""Generate proxy credentials from environment variables.

Reads ~/.config/nanobox/credentials.template.json, substitutes ${VAR}
placeholders from the current environment (plus any .env files passed as
arguments), and writes credentials.json.

Usage:
  nbox passenvs                      # from current env only
  nbox passenvs ~/project/.env       # load .env first, then substitute
  nbox passenvs .env .env.prod       # multiple .env files (later wins)
  nbox passenvs --check .env         # dry-run
"""
import json
import os
import re
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "nanobox"
TEMPLATE = CONFIG_DIR / "credentials.template.json"
OUTPUT = CONFIG_DIR / "credentials.json"

VAR_RE = re.compile(r"\$\{(\w+)}")
ENV_LINE_RE = re.compile(r"^([A-Za-z_]\w*)=(.*)$")


def load_env_file(path: Path, env: dict[str, str]) -> None:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = ENV_LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        env[key] = val


def substitute(value: str, env: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def _replace(m: re.Match[str]) -> str:
        var = m.group(1)
        val = env.get(var)
        if val is None:
            missing.append(var)
            return m.group(0)
        return val

    return VAR_RE.sub(_replace, value), missing


def main() -> int:
    args = sys.argv[1:]
    check_only = "--check" in args
    env_files = [Path(a) for a in args if a != "--check"]

    env: dict[str, str] = dict(os.environ)
    for ef in env_files:
        if not ef.exists():
            print(f"error: {ef} not found", file=sys.stderr)
            return 1
        load_env_file(ef, env)
        print(f"  loaded {ef}", file=sys.stderr)

    if not TEMPLATE.exists():
        print(f"error: template not found: {TEMPLATE}", file=sys.stderr)
        print("  Run 'nbox proxy' first to create it.", file=sys.stderr)
        return 1

    template: dict[str, dict[str, str]] = json.loads(TEMPLATE.read_text())

    result: dict[str, dict[str, str]] = {}
    for host, headers in template.items():
        if host.startswith("_"):
            continue
        resolved: dict[str, str] = {}
        skip = False
        for header_name, header_value in headers.items():
            value, missing = substitute(header_value, env)
            if missing:
                print(f"  skip {host}: {', '.join(missing)} not set", file=sys.stderr)
                skip = True
                break
            resolved[header_name] = value
        if not skip:
            result[host] = resolved

    if check_only:
        for host in result:
            print(f"  ok   {host}", file=sys.stderr)
        print(f"{len(result)} host(s) would be written", file=sys.stderr)
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
    OUTPUT.chmod(0o600)

    if result:
        print(f"wrote {len(result)} host(s) to {OUTPUT}", file=sys.stderr)
    else:
        print(f"warning: no credentials resolved, {OUTPUT} is empty", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
