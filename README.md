# nanobox

Agent-agnostic sandbox that combines [bubblewrap](https://github.com/containers/bubblewrap) and [mitmproxy](https://mitmproxy.org/) to run any command inside a confined Linux user namespace. No root required.

Designed for running AI coding agents (Claude Code, etc.) on shared machines where unrestricted shell access is risky — but works for any command you want to isolate.

## Requirements

- **bubblewrap (bwrap) >= 0.5.0** — needed for `--clearenv` support
- **User namespaces enabled** — verify with `unshare --user true` (if it fails, ask your sysadmin to set `kernel.unprivileged_userns_clone=1`)
- **python3 + PyYAML**
- **mitmproxy** (optional, for credential injection)

## What it does

- Mounts system dirs read-only, gives the project directory read-write access
- Masks secret files (`.env*`) with `/dev/null`, forces `.venv*` read-only
- Hides SSH private keys (only forwards the agent socket)
- Auto-detects NVIDIA GPUs and passes through device nodes
- Optionally injects HTTP credentials via a local mitmproxy (transparent to the sandboxed process)
- Forwards a curated set of environment variables

## Install

```bash
git clone git@github.com:JanRocketMan/nanobox.git ~/nanobox
echo "alias nbox='~/nanobox/nbox'" >> ~/.zshrc
```

## Quick start

```bash
# Create config (opens in $EDITOR)
nbox setup

# Preview the bwrap command without running
nbox status

# Run any command inside the sandbox
nbox run /bin/bash
nbox run claude
nbox run claude --resume
```

## Commands

### `nbox setup`

Creates `~/.config/nanobox/config.yaml` from the default template and opens it in your editor. Checks that `bwrap` and `PyYAML` are installed.

### `nbox run <command> [args...]`

Runs `<command>` inside the sandbox. The current directory is mounted read-write as the project directory. All arguments after the command name are passed through.

```bash
nbox run claude --resume          # resume a Claude session
nbox run /bin/bash                # debug the sandbox interactively
nbox run python train.py --lr 1e-4
```

### `nbox status`

Prints the full `bwrap` command that would be executed, without running it. Useful for debugging mount configuration.

### `nbox proxy`

Creates or opens `~/.config/nanobox/credentials.template.json` for editing. This template maps hostnames to HTTP headers with `${VAR}` placeholders.

### `nbox resolve [.env files...]`

Resolves `${VAR}` placeholders in the credentials template using environment variables (and optional `.env` files), writes the result to `credentials.json`. The proxy auto-starts on `nbox run` when credentials are present.

```bash
nbox resolve                    # resolve from current env
nbox resolve .env .env.prod     # layer .env files (later wins)
nbox resolve --check .env       # dry-run
```

## Config format

The config at `~/.config/nanobox/config.yaml` has four sections:

```yaml
mounts:
  read:         # Read-only mounts (absolute paths or glob patterns)
    - /usr
    - ~/.local/bin
    - ".venv*"  # Glob: forces matching project entries read-only

  write:        # Read-write mounts (project dir is always rw implicitly)
    - ~/.cache
    - ~/.claude

  deny:         # Mask matching project files with /dev/null
    - ".env*"
    - "!*.example"  # Negation: exclude from masking

path:           # PATH inside the sandbox (in order)
  - ~/.local/bin
  - /usr/bin

env:
  forward:      # Forward from host (supports globs like CUDA_*)
    - TERM
    - ANTHROPIC_API_KEY
    - "CUDA_*"

  set:           # Set explicitly
    SHELL: /bin/bash
```

**Path syntax:** `/absolute`, `~/relative` (expands to `$HOME`), or bare glob patterns matched against project directory entries.

## Security model

| Resource | Access |
|---|---|
| Project directory | Read-write |
| `.venv*` in project | Read-only overlay |
| `.env*` in project | Masked (`/dev/null`) |
| System (`/usr`, `/bin`, `/etc`) | Read-only |
| `$HOME` | Empty tmpfs + selective mounts |
| SSH private keys | Hidden (agent socket forwarded) |
| NVIDIA GPUs | Auto-detected, device nodes passed through |
| Network | Shared with host (optionally proxied) |

## Comparison with CubeSandbox

[CubeSandbox](https://github.com/TencentCloud/CubeSandbox) is a KVM-based sandbox service from Tencent designed for AI agent code execution at scale. It's a fundamentally different tool solving a related problem — here's how they compare.

|  | nanobox | CubeSandbox |
|---|---|---|
| **Isolation** | Linux user namespaces (bubblewrap) | KVM micro-VMs (dedicated guest kernel) |
| **Root required** | No | Yes (KVM + systemd daemons) |
| **Setup** | Single script + YAML config | Multi-service deployment (MySQL, Redis, CoreDNS, QEMU, etc.) |
| **Cold start** | ~instant (no VM boot) | <60ms (snapshot cloning) |
| **Memory overhead** | Near zero (namespace, no guest OS) | <5MB per instance (CoW + trimmed runtime) |
| **GPU passthrough** | Yes (auto-detected NVIDIA) | Not documented |
| **Credential injection** | mitmproxy-based (transparent HTTP header injection) | Environment variables |
| **Network isolation** | Shared with host (optionally proxied) | Full eBPF-based per-sandbox network policies |
| **Filesystem model** | Config-driven mount allow/deny lists with glob patterns | OCI image templates with writable layers |
| **Secret masking** | `.env*` files masked at mount level | N/A (isolated VM, no host files exposed) |
| **Target scale** | Single user on a shared machine | Thousands of concurrent agents per node |
| **Platform** | Any Linux with user namespaces | x86_64 Linux with KVM (bare-metal or nested virt) |
| **SDK/API** | CLI (`nbox run`) | E2B-compatible Python SDK + REST API |

**When to use nanobox:** You're a developer running an AI agent (or any tool) on a shared machine and want lightweight filesystem isolation without infrastructure overhead. You want to control exactly which paths are visible, mask secrets, and optionally inject credentials — all from a single YAML config, no root needed.

**When to use CubeSandbox:** You're building a platform that runs untrusted code from many users at scale and need VM-level isolation with dedicated kernels, per-sandbox network policies, and an E2B-compatible SDK. You have the infrastructure to run KVM and the supporting services.

In short: nanobox is a personal dev tool (single script, zero infrastructure), CubeSandbox is a platform service (multi-component, production-scale).

## License

MIT
