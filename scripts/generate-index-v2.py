#!/usr/bin/env python3
from __future__ import annotations
"""Generate V2 structured index.json with calldata/eip712 split.

Output format:
{
  "calldata": { "eip155:{chainId}:{address}": "path/to/descriptor.json" },
  "eip712":   { "eip155:{chainId}:{address}": [{"primaryType": "...", "path": "..."}] }
}
"""

import copy
import json
import os
import sys
from typing import Any

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
        if parts:
            parts.pop()
        relative = relative[3:]
    if not parts:
        return relative
    return "/".join(parts) + "/" + relative


def get_includes_list(descriptor: dict[str, Any]) -> list[str]:
    includes = descriptor.get("includes")
    if isinstance(includes, str):
        return [includes]
    if isinstance(includes, list):
        return [value for value in includes if isinstance(value, str)]
    return []


def merge_values(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = copy.deepcopy(base)
        for key, value in overlay.items():
            if key in merged:
                merged[key] = merge_values(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged
    return copy.deepcopy(overlay)


def extract_index_relevant_fields(descriptor: dict[str, Any]) -> dict[str, Any]:
    relevant: dict[str, Any] = {}

    if isinstance(descriptor.get("context"), dict):
        relevant["context"] = descriptor["context"]

    display = descriptor.get("display")
    if isinstance(display, dict):
        display_relevant: dict[str, Any] = {}
        if isinstance(display.get("formats"), dict):
            display_relevant["formats"] = display["formats"]
        if isinstance(display.get("definitions"), dict):
            display_relevant["definitions"] = display["definitions"]
        if display_relevant:
            relevant["display"] = display_relevant

    return relevant


def load_effective_descriptor(
    abs_path: str,
    rel_path: str,
    warnings: list[str] | None = None,
    depth: int = MAX_INCLUDES_DEPTH,
    stack: tuple[str, ...] = (),
    cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if warnings is None:
        warnings = []
    if cache is None:
        cache = {}

    if rel_path in cache:
        return copy.deepcopy(cache[rel_path])

    if rel_path in stack:
        warnings.append(f"include cycle detected: {' -> '.join((*stack, rel_path))}")
        return {}

    with open(abs_path) as f:
        descriptor = json.load(f)

    merged: dict[str, Any] = {}
    includes = get_includes_list(descriptor)

    if includes and depth <= 0:
        warnings.append(f"max includes depth reached for {rel_path}")
    else:
        for include_ref in includes:
            if "://" in include_ref:
                warnings.append(f"external include skipped: {include_ref} (from {rel_path})")
                continue

            resolved_rel = resolve_relative_path(rel_path, include_ref)
            resolved_abs = os.path.join(REGISTRY_ROOT, resolved_rel)
            if not os.path.exists(resolved_abs):
                warnings.append(f"includes target not found: {resolved_rel} (from {rel_path})")
                continue

            included = load_effective_descriptor(
                resolved_abs,
                resolved_rel,
                warnings=warnings,
                depth=depth - 1,
                stack=(*stack, rel_path),
                cache=cache,
            )
            merged = merge_values(merged, included)

    merged = merge_values(merged, extract_index_relevant_fields(descriptor))
    cache[rel_path] = copy.deepcopy(merged)
    return merged


def extract_primary_types(descriptor: dict[str, Any]) -> set[str]:
    formats = descriptor.get("display", {}).get("formats", {})
    primary_types = set()
    for key in formats:
        pt = key.split("(")[0] if "(" in key else key
        primary_types.add(pt)
    return primary_types


def build_index() -> tuple[dict[str, Any], list[str]]:
    calldata: dict[str, str] = {}
    eip712: dict[str, list[dict[str, str]]] = {}
    warnings: list[str] = []
    cache: dict[str, dict[str, Any]] = {}

    for folder in get_folders():
        abs_folder = os.path.join(REGISTRY_ROOT, folder)
        if not os.path.isdir(abs_folder):
            continue

        for filename in sorted(os.listdir(abs_folder)):
            if not filename.endswith(".json"):
                continue
            if filename.startswith("common-") or filename.startswith("tests"):
                continue

            filepath = os.path.join(abs_folder, filename)
            rel_path = f"{folder}/{filename}"

            with open(filepath) as f:
                raw_descriptor = json.load(f)

            descriptor = load_effective_descriptor(
                filepath,
                rel_path,
                warnings=warnings,
                cache=cache,
            )

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

                primary_types = extract_primary_types(descriptor)
                if not primary_types:
                    if extract_primary_types(raw_descriptor):
                        warnings.append(f"no primaryTypes found for {rel_path}")
                    continue

                for dep in deployments:
                    key = make_key(dep["chainId"], dep["address"])
                    entries = eip712.setdefault(key, [])
                    for pt in sorted(primary_types):
                        entry = {"primaryType": pt, "path": rel_path}
                        if entry not in entries:
                            entries.append(entry)


    index = {
        "calldata": dict(sorted(calldata.items())),
        "eip712": dict(sorted(eip712.items())),
    }
    return index, warnings


def main():
    index, warnings = build_index()

    with open(INDEX_PATH, "w") as f:
        json.dump(index, f, indent=2)
        f.write("\n")

    eip712_entries = sum(len(v) for v in index["eip712"].values())
    print(f"calldata: {len(index['calldata'])} keys")
    print(f"eip712:   {len(index['eip712'])} keys ({eip712_entries} entries)")

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  {warning}")


if __name__ == "__main__":
    main()
