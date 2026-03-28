#!/usr/bin/env python3
"""Generate V2 structured index.json with calldata/eip712 split.

Output format:
{
  "calldata": { "eip155:{chainId}:{address}": "path/to/descriptor.json" },
  "eip712":   { "eip155:{chainId}:{address}": [{"primaryType": "...", "path": "..."}] }
}
"""

import json
import os
import sys

REGISTRY_ROOT = os.path.join(os.path.dirname(__file__), "..")
INDEX_PATH = os.path.join(REGISTRY_ROOT, "index.json")
REGISTRY_DIR = os.path.join(REGISTRY_ROOT, "registry")

MAX_INCLUDES_DEPTH = 3


def get_folders():
    folders = ["ercs"]
    if os.path.isdir(REGISTRY_DIR):
        for name in sorted(os.listdir(REGISTRY_DIR)):
            if os.path.isdir(os.path.join(REGISTRY_DIR, name)):
                folders.append(f"registry/{name}")
    return folders


def make_key(chain_id: int, address: str) -> str:
    return f"eip155:{chain_id}:{address.lower()}"


def resolve_relative_path(base: str, relative: str) -> str:
    """Resolve a relative path against a base file path.

    Mirrors the Rust resolve_relative_path logic.
    """
    if relative.startswith("./"):
        relative = relative[2:]
    dir_part = os.path.dirname(base)
    if not dir_part:
        return relative
    parts = dir_part.split("/")
    while relative.startswith("../"):
        parts.pop()
        relative = relative[3:]
    if not parts:
        return relative
    return "/".join(parts) + "/" + relative


def extract_primary_types(abs_path: str, rel_path: str, depth: int = MAX_INCLUDES_DEPTH) -> set[str]:
    """Extract primaryTypes from a descriptor's format keys, resolving includes."""
    with open(abs_path) as f:
        descriptor = json.load(f)

    formats = descriptor.get("display", {}).get("formats", {})
    primary_types = set()
    for key in formats:
        pt = key.split("(")[0] if "(" in key else key
        primary_types.add(pt)

    if primary_types:
        return primary_types

    includes = descriptor.get("includes")
    if includes and depth > 0:
        resolved_rel = resolve_relative_path(rel_path, includes)
        resolved_abs = os.path.join(REGISTRY_ROOT, resolved_rel)
        if os.path.exists(resolved_abs):
            return extract_primary_types(resolved_abs, resolved_rel, depth - 1)
        else:
            print(f"  WARNING: includes target not found: {resolved_rel} (from {rel_path})", file=sys.stderr)

    return primary_types


def main():
    calldata = {}
    eip712 = {}
    warnings = []

    for folder in get_folders():
        abs_folder = os.path.join(REGISTRY_ROOT, folder)
        if not os.path.isdir(abs_folder):
            continue

        for filename in sorted(os.listdir(abs_folder)):
            if not filename.endswith(".json"):
                continue
            # Skip test files, common/shared files, schema files
            if filename.startswith("common-") or filename.startswith("tests"):
                continue

            filepath = os.path.join(abs_folder, filename)
            rel_path = f"{folder}/{filename}"

            with open(filepath) as f:
                descriptor = json.load(f)

            ctx = descriptor.get("context", {})

            if "contract" in ctx:
                deployments = ctx["contract"].get("deployments", [])
                for dep in deployments:
                    key = make_key(dep["chainId"], dep["address"])
                    if key in calldata and calldata[key] != rel_path:
                        warnings.append(f"calldata collision: {key} -> {calldata[key]} vs {rel_path}")
                    calldata[key] = rel_path

            elif "eip712" in ctx:
                deployments = ctx["eip712"].get("deployments", [])
                if not deployments:
                    continue

                primary_types = extract_primary_types(filepath, rel_path)
                if not primary_types:
                    warnings.append(f"no primaryTypes found for {rel_path}")
                    continue

                for dep in deployments:
                    key = make_key(dep["chainId"], dep["address"])
                    entries = eip712.setdefault(key, [])
                    for pt in sorted(primary_types):
                        entry = {"primaryType": pt, "path": rel_path}
                        if entry not in entries:
                            entries.append(entry)

    # Sort keys for deterministic output
    index = {
        "calldata": dict(sorted(calldata.items())),
        "eip712": dict(sorted(eip712.items())),
    }

    with open(INDEX_PATH, "w") as f:
        json.dump(index, f, indent=2)
        f.write("\n")

    # Summary
    eip712_entries = sum(len(v) for v in eip712.values())
    print(f"calldata: {len(calldata)} keys")
    print(f"eip712:   {len(eip712)} keys ({eip712_entries} entries)")

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(f"  {w}")


if __name__ == "__main__":
    main()
