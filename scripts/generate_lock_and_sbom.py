"""Regenerate sbom.json (CycloneDX) from requirements.lock pins.

The lockfile itself is owned by scripts/pin_hashes.py (full transitive
closure + PyPI hashes). This script NEVER rewrites requirements.lock —
it only rebuilds the SBOM so the two artifacts cannot drift.

Usage:
    python scripts/pin_hashes.py            # lock (+ Dockerfile digest)
    python scripts/generate_lock_and_sbom.py  # sbom.json from the lock
"""

import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = ROOT / "requirements.lock"
SBOM_FILE = ROOT / "sbom.json"


def lock_pins() -> list:
    pins = []
    for line in LOCK_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-+!]+)", line.strip())
        if m:
            pins.append((m.group(1).lower().replace("_", "-"), m.group(2)))
    return pins


def lock_hashes() -> dict:
    """Map package -> [sha256...] parsed from --hash lines following each pin."""
    hashes: dict = {}
    current = None
    for line in LOCK_FILE.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)==", s)
        if m:
            current = m.group(1).lower().replace("_", "-")
            hashes.setdefault(current, [])
            continue
        hm = re.match(r"--hash=sha256:([0-9a-f]{64})", s)
        if hm and current:
            hashes[current].append(hm.group(1))
    return hashes


def main() -> None:
    if not LOCK_FILE.exists():
        print("requirements.lock missing; run python scripts/pin_hashes.py first", file=sys.stderr)
        return 1
    pins = lock_pins()
    if not pins:
        print("No pins found in requirements.lock", file=sys.stderr)
        return 1
    hashes = lock_hashes()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    components = []
    for name, version in pins:
        comp = {
            "type": "library",
            "bom-ref": f"pkg:pypi/{name}@{version}",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name}@{version}",
            "scope": "required",
        }
        if hashes.get(name):
            comp["hashes"] = [{"alg": "SHA-256", "content": h} for h in hashes[name][:4]]
        components.append(comp)
    sbom = {
        "$schema": "http://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "timestamp": stamp,
            "component": {
                "type": "application",
                "name": "deepans-code",
                "version": "3.0.0",
            },
        },
        "components": components,
    }
    SBOM_FILE.write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {SBOM_FILE.name} (CycloneDX 1.6, {len(components)} components from lock)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
