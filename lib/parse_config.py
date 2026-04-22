#!/usr/bin/env python3
"""Parse nanobox YAML config and output bash-evaluable arrays."""
import shlex
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: PyYAML not installed. Run: uv pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def expand_home(path: str) -> str:
    home = str(Path.home())
    if path == "~":
        return home
    if path.startswith("~/"):
        return home + path[1:]
    return path


def is_pattern(path: str) -> bool:
    return not path.startswith("/") and not path.startswith("~")


def bash_array(name, items):
    escaped = [shlex.quote(item) for item in items]
    return f"{name}=({' '.join(escaped)})"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: parse_config.py <config.yaml>", file=sys.stderr)
        return 1

    config_path = Path(sys.argv[1])
    if not config_path.exists():
        print(f"error: config not found: {config_path}", file=sys.stderr)
        return 1

    with open(config_path) as f:
        config = yaml.safe_load(f)

    mounts = config.get("mounts", {})
    env = config.get("env", {})
    path_dirs = config.get("path", [])

    ro_dirs = []
    ro_patterns = []
    for entry in mounts.get("read", []):
        if entry is None:
            continue
        entry = str(entry)
        if is_pattern(entry):
            ro_patterns.append(entry)
        else:
            ro_dirs.append(expand_home(entry))

    rw_dirs = []
    for entry in mounts.get("write", []):
        if entry is None:
            continue
        rw_dirs.append(expand_home(str(entry)))

    deny_patterns = []
    deny_negations = []
    for entry in mounts.get("deny", []):
        if entry is None:
            continue
        entry = str(entry)
        if entry.startswith("!"):
            deny_negations.append(entry[1:])
        else:
            deny_patterns.append(entry)

    env_forward = []
    for entry in env.get("forward", []):
        if entry is None:
            continue
        env_forward.append(str(entry))

    env_set_keys = []
    env_set_vals = []
    for key, val in env.get("set", {}).items():
        if val is None:
            continue
        env_set_keys.append(str(key))
        env_set_vals.append(expand_home(str(val)))

    path_expanded = []
    for entry in path_dirs:
        if entry is None:
            continue
        path_expanded.append(expand_home(str(entry)))

    print(bash_array("RO_DIRS", ro_dirs))
    print(bash_array("RO_PATTERNS", ro_patterns))
    print(bash_array("RW_DIRS", rw_dirs))
    print(bash_array("DENY_PATTERNS", deny_patterns))
    print(bash_array("DENY_NEGATIONS", deny_negations))
    print(bash_array("ENV_FORWARD", env_forward))
    print(bash_array("ENV_SET_KEYS", env_set_keys))
    print(bash_array("ENV_SET_VALS", env_set_vals))
    print(bash_array("SANDBOX_PATH_DIRS", path_expanded))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
