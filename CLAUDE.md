# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

nanobox is a single-script Linux sandbox that wraps bubblewrap (`bwrap`) and optionally mitmproxy to run any command in an isolated user namespace. No root required. Primary use case: running AI coding agents on shared machines.

## Project layout

```
nbox                           # Main bash CLI (~440 lines) - all orchestration logic
lib/
  parse_config.py              # YAML config → bash-evaluable arrays (eval'd by nbox)
  passenvs.py                  # ${VAR} template resolver → credentials.json
  inject_credentials.py        # mitmproxy addon that injects HTTP headers per-host
  random_port.py               # print a free ephemeral loopback port (proxy port)
  wait_port.py                 # wait until a loopback TCP port accepts connections
default-config.yaml            # Template copied to ~/.config/nanobox/config.yaml on setup
```

No build system, no package manager, no tests. The deliverable is the `nbox` bash script + its `lib/` helpers.

## How to run

```bash
./nbox setup                              # creates config, checks deps (bwrap, PyYAML)
./nbox run /bin/bash                      # run a command inside the sandbox
./nbox run --extra-dir ~/other claude     # mount additional directories
./nbox status                             # preview the full bwrap invocation
./nbox proxy                              # create/edit credentials template
./nbox resolve [.env files]               # resolve template -> credentials.json
```

## Architecture

The execution flow for `nbox run` is:

1. `parse_config.py` reads `~/.config/nanobox/config.yaml` and outputs bash arrays (`RO_DIRS`, `RW_DIRS`, `DENY_PATTERNS`, `ENV_FORWARD`, etc.) that nbox `eval`s
2. `build_bwrap()` assembles a `bwrap --clearenv` command from those arrays: namespace flags, mount layers, env vars, GPU devices, SSH agent socket, proxy config
3. If `credentials.json` exists, a per-session proxy starts: mitmdump on a random loopback port with `inject_credentials.py` as its addon and a random auth token, plus a socat unix-socket bridge (host socket `0600` -> mitmdump TCP)
4. `bwrap --clearenv [args] -- <sandbox command>` runs as a child; a wrapper inside the sandbox starts socat on `127.0.0.1:3128` forwarding to the bind-mounted socket. The EXIT trap tears the proxy session down

The sandbox runs in an isolated network namespace: no direct network, HTTPS only through the enforced proxy.

The mount layering order matters: tmpfs home -> ro system dirs -> rw user dirs -> rw project dir (+ extra dirs) -> ro overlays (`.venv*`) -> deny masks (`.env*` -> `/dev/null`). Later mounts override earlier ones for the same path. Extra dirs passed via `--extra-dir` receive the same treatment as the project dir (rw bind + ro overlays + deny masks).

## Config ↔ bash array mapping

`parse_config.py` classifies config entries by syntax: entries starting with `/` or `~` become absolute paths (in `*_DIRS` arrays); bare entries become glob patterns (in `*_PATTERNS` arrays). Globs are matched against the project directory at mount time in the bash script.

## Key conventions

- Never inline Python into `nbox`; all Python helpers live in `lib/` and are invoked as `python3 "$NBOX_DIR/lib/<script>.py"` (stdout for machine output, stderr for human messages)
- Python helpers output to stdout for machine consumption (bash arrays, JSON) and to stderr for human messages
- Per-user ephemeral state lives in `$NBOX_RUNTIME` (`$XDG_RUNTIME_DIR` or `/tmp/nbox-$UID`)
- Proxy sessions are per-run: random loopback port, random auth token, session dir `0700` under `$NBOX_RUNTIME/nbox/`, socket `0600`; the EXIT trap kills the process group and removes the session dir
- Never ship an egress-policy or proxy change that could block other running agents without first inventorying their required endpoints and confirming with the operator. A single host missing from a default-deny allow list breaks the live harness mid-run. Default to fail-open for hostnames unless the operator explicitly opts into strict mode; keep security-critical blocks (bare IPs, private/metadata ranges, SNI/Host mismatch, HTTPS-only credential injection) fail-closed
- Temporary files use `mktemp /tmp/nbox-*.XXXXXX` and are cleaned up via an EXIT trap
- SSH private keys are never mounted; only the agent socket is forwarded
- The `NBOX=1` env var is set inside the sandbox for detection
- Credentials file is written with `0o600` permissions
