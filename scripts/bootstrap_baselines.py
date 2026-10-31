"""Clone pinned source baselines only; never install packages or download data."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "configs" / "baselines.lock.json"


def load_lock(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported baseline lock schema")
    repositories = data.get("repositories", [])
    if not repositories:
        raise ValueError("Baseline lock has no repositories")
    names: set[str] = set()
    for repo in repositories:
        name = repo.get("name", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or name in {".", ".."}:
            raise ValueError(f"Invalid repository directory name: {name!r}")
        if name in names:
            raise ValueError(f"Duplicate repository name: {name}")
        names.add(name)
        if not re.fullmatch(r"[0-9a-f]{40}", repo.get("commit", "")):
            raise ValueError(f"Repository {name} needs a full pinned commit")
        if not repo.get("url", "").startswith("https://github.com/"):
            raise ValueError(f"Repository {name} must have an HTTPS GitHub source")
    return repositories


def git_command(git: str, ssl_backend: str | None, *args: str) -> list[str]:
    prefix = [git]
    if ssl_backend:
        prefix.extend(["-c", f"http.sslBackend={ssl_backend}"])
    return [*prefix, *args]


def run_git(git: str, ssl_backend: str | None, *args: str, check: bool = True):
    return subprocess.run(
        git_command(git, ssl_backend, *args),
        text=True, capture_output=True, check=check,
    )


def inspect_checkout(path: Path, repo: dict[str, str], git: str, ssl_backend: str | None) -> dict:
    result = {"name": repo["name"], "path": str(path), "expected": repo["commit"]}
    if not path.is_dir():
        return {**result, "status": "missing"}
    head = run_git(git, ssl_backend, "-C", str(path), "rev-parse", "HEAD", check=False)
    if head.returncode:
        return {**result, "status": "not_a_git_checkout"}
    origin = run_git(git, ssl_backend, "-C", str(path), "remote", "get-url", "origin", check=False)
    if origin.returncode:
        return {**result, "status": "origin_missing"}
    if origin.stdout.strip().removesuffix(".git") != repo["url"].removesuffix(".git"):
        return {**result, "status": "origin_mismatch"}
    dirty = run_git(git, ssl_backend, "-C", str(path), "status", "--porcelain").stdout.strip()
    actual = head.stdout.strip()
    return {
        **result, "actual": actual,
        "status": "dirty" if dirty else "ok" if actual == repo["commit"] else "commit_mismatch",
    }


def bootstrap(
    repositories: list[dict[str, str]], destination: Path, git: str,
    *, ssl_backend: str | None = None, check_only: bool = False,
) -> list[dict]:
    destination = destination.resolve()
    results = []
    for repo in repositories:
        path = destination / repo["name"]
        if not path.resolve().is_relative_to(destination):
            raise ValueError("Repository destination escaped the upstream directory")
        status = inspect_checkout(path, repo, git, ssl_backend)
        if check_only or status["status"] == "ok":
            results.append(status)
            continue
        if status["status"] not in {"missing", "commit_mismatch"}:
            results.append(status)
            continue
        if status["status"] == "missing":
            destination.mkdir(parents=True, exist_ok=True)
            run_git(git, ssl_backend, "clone", "--no-checkout", "--filter=blob:none", repo["url"], str(path))
        has_commit = run_git(
            git, ssl_backend, "-C", str(path), "cat-file", "-e", f"{repo['commit']}^{{commit}}", check=False,
        )
        if has_commit.returncode:
            run_git(git, ssl_backend, "-C", str(path), "fetch", "--depth=1", "origin", repo["commit"])
        run_git(git, ssl_backend, "-C", str(path), "checkout", "--detach", repo["commit"])
        results.append(inspect_checkout(path, repo, git, ssl_backend))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--destination", type=Path, default=ROOT / ".upstreams")
    parser.add_argument("--check", action="store_true", help="Read-only check; no network or checkout changes")
    parser.add_argument("--repo", action="append", help="Only named entries; repeat for multiple repositories")
    parser.add_argument("--git-bin", default=os.environ.get("CALC_GIT_BIN") or shutil.which("git"))
    parser.add_argument("--ssl-backend", choices=("openssl", "schannel"), default=None,
                        help="Optional per-command Git TLS backend; leave unset on normal Linux installs")
    args = parser.parse_args(argv)
    if not args.git_bin:
        parser.error("git was not found; pass --git-bin or set CALC_GIT_BIN")
    try:
        repositories = load_lock(args.lock)
        if args.repo:
            unknown = set(args.repo) - {repo["name"] for repo in repositories}
            if unknown:
                parser.error("Unknown repositories: " + ", ".join(sorted(unknown)))
            repositories = [repo for repo in repositories if repo["name"] in args.repo]
        results = bootstrap(
            repositories, args.destination, args.git_bin,
            ssl_backend=args.ssl_backend, check_only=args.check,
        )
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Baseline bootstrap failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(results, indent=2))
    return 0 if all(result["status"] == "ok" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
