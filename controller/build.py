"""What this controller is actually running, computed from its own files.

Why
---

Two live runs were spent against a controller several commits behind the code
that had just been written and tested. Both times the symptom was confusing --
an API silently ignoring a field it did not know, an activation issued that the
current code would have refused -- and both times the diagnosis took longer
than the fix.

A version number in a constant would not have helped, because the failure is
forgetting to deploy, and a forgotten deploy leaves the old constant behind
along with the old code. The identifier has to be derived from the bytes that
are actually loaded, so it cannot be right unless the files are.

What it is
----------

A SHA-256 over a manifest of `(logical name, file digest)` for every Python
file the hub serves: `hub.py` and the `controller` package. Sorted, so it does
not depend on directory order, and keyed by logical name so the same tree
produces the same id whether it sits at `hub/hub.py` in the repository or
`app/hub.py` in the container.

Per-file digests are reported alongside the id. An id mismatch says only "these
differ"; the file list says which one, which is the difference between a
minute's work and an afternoon's.

What it is not
--------------

Not a git commit id. The deployed tree has no `.git`, and a commit id would
have to be written in by whatever does the deploying -- which is exactly the
step that gets forgotten. This asks the files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(root: Path) -> Dict[str, str]:
    """Logical name -> file digest, for everything the hub serves.

    `root` is the directory holding `hub.py` and `controller/`. In the
    container that is `/app`; in the repository the two live in different
    directories, so `from_repository` maps them onto the same names.
    """
    root = Path(root)
    files: Dict[str, str] = {}

    hub = root / "hub.py"

    if hub.exists():
        files["hub.py"] = _digest(hub)

    package = root / "controller"

    if package.is_dir():
        for path in sorted(package.glob("*.py")):
            files[f"controller/{path.name}"] = _digest(path)

    return files


def build_id(files: Dict[str, str]) -> str:
    """A single identifier for a manifest.

    Newline-joined `name:digest` rather than a dict hash, because a dict's
    repr is not stable across Python versions and this value is compared
    between two different processes.
    """
    joined = "\n".join(f"{name}:{digest}" for name, digest in sorted(files.items()))

    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def describe(root: Path) -> dict:
    """The manifest and its id, as the status route reports them."""
    files = manifest(root)

    return {"build_id": build_id(files), "files": files}


def from_repository(repo_root: Path) -> dict:
    """The build a repository checkout *would* deploy.

    `hub/hub.py` in the repository becomes `hub.py`, because that is where it
    lands in the container. Without this the same tree would produce two
    different ids depending on which side computed it, and the check would fail
    permanently for a reason that has nothing to do with deployment.
    """
    repo_root = Path(repo_root)
    files: Dict[str, str] = {}

    hub = repo_root / "hub" / "hub.py"

    if hub.exists():
        files["hub.py"] = _digest(hub)

    package = repo_root / "controller"

    if package.is_dir():
        for path in sorted(package.glob("*.py")):
            files[f"controller/{path.name}"] = _digest(path)

    return {"build_id": build_id(files), "files": files}


def compare(expected: dict, deployed: dict) -> dict:
    """Why two builds differ, or that they do not.

    Reports missing, extra and differing files separately. "The deployed tree
    is missing a module" and "a module was edited" are different mistakes with
    different fixes, and a single boolean hides which one happened.
    """
    want = expected.get("files", {})
    have = deployed.get("files", {})

    missing = sorted(set(want) - set(have))
    extra = sorted(set(have) - set(want))
    differing = sorted(
        name for name in set(want) & set(have) if want[name] != have[name]
    )

    return {
        "match": expected.get("build_id") == deployed.get("build_id"),
        "expected_build_id": expected.get("build_id"),
        "deployed_build_id": deployed.get("build_id"),
        "missing_from_deployment": missing,
        "not_in_the_repository": extra,
        "differing": differing,
    }
