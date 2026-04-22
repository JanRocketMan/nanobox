# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

nanobox is a single-script Linux sandbox that wraps bubblewrap (`bwrap`) and optionally mitmproxy to run any command in an isolated user namespace. No root required. Primary use case: running AI coding agents on shared machines.

## Project layout

```
nbox                           # Main bash CLI (~395 lines) — all orchestration logic
lib/
  parse_config.py              # YAML config → bash-evaluable arrays (eval'd by nbox)
  passenvs.py                  # ${VAR} template resolver → credentials.json
  inject_credentials.py        # mitmproxy addon that injects HTTP headers per-host
default-config.yaml            # Template copied to ~/.config/nanobox/config.yaml on setup
```

No build system, no package manager, no tests. The deliverable is the `nbox` bash script + its `lib/` helpers.

## How to run

```bash
./nbox setup                   # creates config, checks deps (bwrap, PyYAML)
./nbox run /bin/bash           # run a command inside the sandbox
./nbox status                  # preview the full bwrap invocation without executing
./nbox proxy                   # create/edit credentials template
./nbox resolve [.env files]    # resolve template → credentials.json
```

## Architecture

The execution flow for `nbox run` is:

1. `parse_config.py` reads `~/.config/nanobox/config.yaml` and outputs bash arrays (`RO_DIRS`, `RW_DIRS`, `DENY_PATTERNS`, `ENV_FORWARD`, etc.) that nbox `eval`s
2. `build_bwrap()` assembles a `bwrap --clearenv` command from those arrays: namespace flags, mount layers, env vars, GPU devices, SSH agent socket, proxy config
3. If `credentials.json` exists, mitmdump starts as a background proxy with `inject_credentials.py` as its addon
4. `exec bwrap --clearenv [args] -- <command>` replaces the shell

The mount layering order matters: tmpfs home → ro system dirs → rw user dirs → rw project dir → ro overlays (`.venv*`) → deny masks (`.env*` → `/dev/null`). Later mounts override earlier ones for the same path.

## Config ↔ bash array mapping

`parse_config.py` classifies config entries by syntax: entries starting with `/` or `~` become absolute paths (in `*_DIRS` arrays); bare entries become glob patterns (in `*_PATTERNS` arrays). Globs are matched against the project directory at mount time in the bash script.

## Key conventions

- Python helpers output to stdout for machine consumption (bash arrays, JSON) and to stderr for human messages
- Per-user ephemeral state lives in `$NBOX_RUNTIME` (`$XDG_RUNTIME_DIR` or `/tmp/nbox-$UID`): proxy PID/log, SSH agent socket
- Proxy port is derived from UID (`18080 + uid % 10000`) so multiple users don't collide
- Temporary files use `mktemp /tmp/nbox-*.XXXXXX` and are cleaned up via an EXIT trap
- SSH private keys are never mounted; only the agent socket is forwarded
- The `NBOX=1` env var is set inside the sandbox for detection
- Credentials file is written with `0o600` permissions
