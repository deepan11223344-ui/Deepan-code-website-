"""Regenerate requirements.lock: full transitive closure, hash-checked.

Usage: python scripts/pin_hashes.py
- Resolves the runtime dependency closure from INSTALLED metadata
  (direct deps from pyproject [project].dependencies + [full] extra),
  so the lock contains every transitive package pip needs.
- Fetches sha256 hashes from the PyPI JSON API (wheels preferred,
  linux-relevant narrowed, sdist fallback) for hash-checking installs.
- Updates the Dockerfile base digest to the current manifest digest.

Requires network once; output is committed for hermetic builds.
Install with: pip install --require-hashes -r requirements.lock
"""

import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements.lock"
DOCKERFILE = ROOT / "Dockerfile"
PYPROJECT = ROOT / "pyproject.toml"
IMAGE = "3.12.7-slim-bookworm"


def direct_dep_names() -> list:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = list(data.get("project", {}).get("dependencies", []))
    deps += list(data.get("project", {}).get("optional-dependencies", {}).get("full", []))
    names = []
    for dep in deps:
        base = dep.strip().split(";")[0].split("[")[0]
        for sep in (">=", "==", "~=", "!=", "<", ">", " "):
            if sep in base:
                base = base.split(sep)[0]
        base = base.strip().lower().replace("_", "-")
        if base and base not in names:
            names.append(base)
    return sorted(names)


def closure(direct: list) -> dict:
    """Walk installed Requires-Dist closure. Returns {normname: version}."""
    pinned: dict = {}
    queue = list(direct)
    while queue:
        name = queue.pop(0)
        key = name.lower().replace("_", "-")
        if key in pinned:
            continue
        try:
            ver = metadata.version(name)
        except metadata.PackageNotFoundError:
            try:
                ver = metadata.version(name.replace("-", "_"))
            except metadata.PackageNotFoundError:
                print(f"WARNING: not installed, skipped: {name}", file=sys.stderr)
                continue
        pinned[key] = ver
        try:
            reqs = metadata.requires(name) or []
        except metadata.PackageNotFoundError:
            reqs = []
        for req in reqs:
            # Honor environment markers via packaging when available:
            # skip extras (extra == ...) and non-applicable platforms.
            try:
                from packaging.requirements import Requirement as _Req

                parsed = _Req(req)
                if parsed.marker is not None and not parsed.marker.evaluate():
                    continue
                base = parsed.name
            except Exception:
                if "extra ==" in req or "extra==" in req:
                    continue
                base = req.split(";")[0].split("[")[0].strip()
            for sep in (">=", "==", "~=", "!=", "<", ">", " ", "("):
                if sep in base:
                    base = base.split(sep)[0]
            base = base.strip().lower().replace("_", "-")
            if base and base not in pinned:
                queue.append(base)
    return pinned


def relevant_hashes(name: str, version: str) -> list:
    r = httpx.get(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30)
    r.raise_for_status()
    urls = r.json().get("urls", [])
    scored = []
    for u in urls:
        fn = u["filename"]
        digest = u["digests"]["sha256"]
        if fn.endswith(".tar.gz"):
            scored.append((3, digest))
        elif "py3-none-any" in fn or "py2.py3-none-any" in fn:
            scored.append((0, digest))
        elif "manylinux" in fn or "musllinux" in fn:
            scored.append((1, digest))
        elif fn.endswith(".whl"):
            scored.append((2, digest))
    scored.sort()
    # keep best per priority class + cap total (pip needs only the file it fetches)
    seen, out = set(), []
    for prio, digest in scored:
        if prio not in seen or len(out) < 4:
            out.append(digest)
            seen.add(prio)
        if len(out) >= 8:
            break
    return out


def main() -> int:
    direct = direct_dep_names()
    pinned = closure(direct)
    print(f"Closure: {len(pinned)} packages from {len(direct)} direct")

    blocks = []
    for name in sorted(pinned):
        ver = pinned[name]
        try:
            hashes = relevant_hashes(name, ver)
        except Exception as e:
            print(f"WARNING: hashes unavailable for {name}=={ver}: {e}", file=sys.stderr)
            continue
        if not hashes:
            print(f"WARNING: no files for {name}=={ver}", file=sys.stderr)
            continue
        lines = [f"{name}=={ver} \\"]
        for i, h in enumerate(hashes):
            sep = " \\" if i < len(hashes) - 1 else ""
            lines.append(f"    --hash=sha256:{h}{sep}")
        blocks.append("\n".join(lines))

    header = "\n".join([
        "# Full transitive lockfile for deepans-code (hash-checked).",
        "# Generated via: python scripts/pin_hashes.py (installed closure + PyPI JSON API).",
        "# Install reproducibly with: pip install --require-hashes -r requirements.lock",
        "# Regenerate pins after version bumps with the same script.",
        "",
    ])
    LOCK.write_text(header + "\n".join(blocks) + "\n", encoding="utf-8")
    print(f"Wrote {LOCK} ({len(blocks)} packages)")

    tok = httpx.get(
        "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/python:pull",
        timeout=20,
    ).json()["token"]
    m = httpx.get(
        f"https://registry-1.docker.io/v2/library/python/manifests/{IMAGE}",
        headers={
            "Authorization": "Bearer " + tok,
            "Accept": "application/vnd.docker.distribution.manifest.list.v2+json",
        },
        timeout=20,
    )
    m.raise_for_status()
    digest = m.headers["docker-content-digest"]
    df = DOCKERFILE.read_text(encoding="utf-8")
    df_new = re.sub(r"^FROM python:[^\s]+.*$", f"FROM python:{IMAGE}@{digest}", df, count=1, flags=re.M)
    DOCKERFILE.write_text(df_new, encoding="utf-8")
    print(f"Pinned Dockerfile to FROM python:{IMAGE}@{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
