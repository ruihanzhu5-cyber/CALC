"""Transfer selected inherited variables to a root-private systemd EnvironmentFile.

Only variable names and a /run/calc path are command arguments. Values are never
printed, put in process arguments, or written to the persistent experiment tree.
"""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("names", nargs="+")
    args = parser.parse_args()
    if args.path.parent != Path("/run/calc") or args.path.suffix != ".env":
        raise ValueError("Environment files must be directly inside /run/calc")
    args.path.parent.mkdir(mode=0o700, exist_ok=True)
    args.path.parent.chmod(0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    fd = os.open(args.path, flags, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        for name in args.names:
            if not name.replace("_", "").isalnum():
                raise ValueError("Invalid environment name")
            value = os.environ.get(name)
            if value is not None:
                if "\n" in value or "\r" in value:
                    raise ValueError("Multiline environment values are unsupported")
                handle.write(name + "=" + json.dumps(value, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
