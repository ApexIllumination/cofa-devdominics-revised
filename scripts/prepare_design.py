"""Download pinned public design resources into this kit's local cache."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

KIT = Path(__file__).resolve().parents[1]
CACHE = KIT / ".design-tools"
SOURCES = json.loads((KIT / "integrations/design-sources.json").read_text())


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def prepare(source):
    name, commit = source["name"], source["commit"]
    entry = Path(source["path"])
    dest = CACHE / name / commit
    target = dest / entry.name
    if target.is_file():
        return target
    dest.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=dest.parent) as temporary:
        tmp = Path(temporary)
        repo = tmp / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "remote", "add", "origin", "https://github.com/" + source["repository"] + ".git")
        git(repo, "config", "remote.origin.promisor", "true")
        git(repo, "config", "remote.origin.partialclonefilter", "blob:none")
        folder = entry.name == "SKILL.md"
        pattern = "/" + (entry.parent.as_posix() + "/" if folder else entry.as_posix())
        git(repo, "sparse-checkout", "set", "--no-cone", pattern)
        git(repo, "fetch", "--quiet", "--no-tags", "--filter=blob:none", "--depth=1", "origin", commit)
        git(repo, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", commit)
        if not (repo / entry).is_file():
            raise ValueError(f"Missing pinned file: {entry}")
        ready = tmp / "ready"
        if folder:
            shutil.copytree(repo / entry.parent, ready, symlinks=True)
        else:
            ready.mkdir()
            shutil.copy2(repo / entry, ready / entry.name)
        try:
            ready.rename(dest)
        except OSError:
            if not target.is_file():
                raise
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="resource names; default: all")
    parser.add_argument("--list", action="store_true", help="show names without downloading")
    args = parser.parse_args()
    known = {s["name"] for s in SOURCES}
    if set(args.names) - known:
        parser.error("Unknown name; see --list")
    failed = False
    for source in SOURCES:
        name = source["name"]
        if args.list:
            print(name)
        elif not args.names or name in args.names:
            try:
                print(prepare(source).relative_to(KIT), flush=True)
            except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                print(f"{name}: {exc}", file=sys.stderr)
                failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
