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
git clone https://github.com/JanRocketMan/nanobox.git ~/nanobox
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

## Comparison with alternatives

There are several tools for sandboxing AI coding agents and general-purpose commands. Here's how they compare.

|  | nanobox | [nono](https://github.com/anthropics/nono) | [Claude Code sandbox](https://docs.anthropic.com/en/docs/claude-code/security) | [E2B](https://e2b.dev) | [Firejail](https://firejail.wordpress.com) | [CubeSandbox](https://github.com/TencentCloud/CubeSandbox) |
|---|---|---|---|---|---|---|
| **Isolation** | User namespaces (bwrap) | Landlock LSM / Seatbelt | bwrap / Seatbelt | Firecracker microVMs (KVM) | Namespaces + seccomp-BPF | KVM micro-VMs |
| **Root required** | No | No | No | Yes (KVM) / N/A (cloud) | SUID binary | Yes (KVM + systemd) |
| **Setup** | Single script + YAML | Single binary + profiles | Built-in (`/sandbox`) | `pip install e2b` + API key | Single binary, 900+ profiles | Multi-service deployment |
| **Cold start** | ~instant | ~instant | ~instant | 125–180ms | ~instant | <60ms (snapshot cloning) |
| **GPU passthrough** | Yes (auto-detect NVIDIA) | Not documented | Not documented | Partial | Manual, fragile | Not documented |
| **Credential injection** | mitmproxy header injection | Phantom-token proxy | Custom proxy config (BYO) | Env vars (proxy in dev) | None | Environment variables |
| **Network isolation** | Shared (optional proxy) | Proxy allowlist + Landlock TCP | Proxy with domain allowlist | VM-level + rate limiting | Namespace (`--net=none` or bridge) | eBPF per-sandbox policies |
| **Filesystem model** | Mount allow/deny + globs | Capability allowlist (default-deny) | CWD rw + configurable paths | Isolated VM (snapshots) | Blacklist/whitelist + overlays | OCI images + writable layers |
| **Secret masking** | `.env*` → `/dev/null` | Keys/creds blocked; phantom tokens | `denyRead`/`denyWrite` rules | N/A (VM isolation) | Blacklist via `disable-common.inc` | N/A (VM isolation) |
| **Target scale** | Single developer | Developer to CI/K8s | Single dev / enterprise managed | Platform (millions concurrent) | Single-user desktop/server | Thousands per node |
| **Platform** | Linux (user namespaces) | Linux 5.13+, macOS, WSL2 | macOS, Linux, WSL2 | Cloud / Linux + KVM | Linux 3.x+ | x86_64 Linux + KVM |
| **SDK/API** | CLI (`nbox run`) | Rust lib + Python/TS/Go + CLI | npm package + CLI | Python/JS/Go SDKs + REST | CLI only | E2B-compatible SDK + REST |

**When to use nanobox:** You're running an AI agent (or any command) on a shared Linux machine and want lightweight mount-driven isolation — control exactly which paths are visible, mask secrets, inject credentials via proxy — from a single YAML config with no root, no VMs, no infrastructure.

**When to use nono:** You want cross-platform (Linux + macOS) kernel-level sandboxing with a default-deny security model and built-in credential proxying via phantom tokens. Stronger isolation guarantees than namespace-only approaches, but requires newer kernels for full features.

**When to use Claude Code sandbox:** You're already using Claude Code and want one-command sandboxing (`/sandbox`) with managed domain allowlists and configurable filesystem permissions. No extra tooling needed.

**When to use E2B:** You're building a platform that runs untrusted code from many users at scale and need full VM isolation with an SDK. Cloud-managed, so no infrastructure to maintain.

**When to use Firejail:** You want to sandbox desktop applications or server processes on Linux with fine-grained seccomp + namespace controls. 900+ pre-built profiles for common apps. Not designed for AI agent workflows.

**When to use CubeSandbox:** You need KVM-level isolation at platform scale with eBPF network policies and an E2B-compatible SDK, and you have the infrastructure to run KVM + supporting services.

## License

MIT
