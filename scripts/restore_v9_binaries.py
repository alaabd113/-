#!/usr/bin/env python3
"""Restore four original binary files after cloning the GoldStation V9 repository.

Binary pieces are stored in Git as Base64 text solely because the connected
GitHub uploader accepts UTF-8 content, not arbitrary bytes. SHA256 verifies
EVERY decoded part and final output. No secrets or broker connection required.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import lzma
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "binary_assets" / "MANIFEST.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def restore_one(spec: dict, check_only: bool = False) -> str:
    output = (ROOT / spec["path"]).resolve()
    if not output.is_relative_to(ROOT.resolve()):
        raise ValueError("Manifest path escapes repository")
    if output.is_file() and output.stat().st_size == spec["size"] and sha256(output) == spec["sha256"]:
        return "VERIFIED_EXISTING " + spec["path"]
    if check_only:
        raise RuntimeError("Missing or invalid restored binary: " + spec["path"])

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="goldstation_rebuild_") as directory:
        encoded = Path(directory) / "combined.transfer"
        with encoded.open("wb") as dest:
            for part in spec["chunks"]:
                path = (ROOT / part["file"]).resolve()
                if not path.is_relative_to(ROOT.resolve()):
                    raise ValueError("Chunk path escapes repository")
                data = base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
                if len(data) != part["size"] or hashlib.sha256(data).hexdigest() != part["sha256"]:
                    raise RuntimeError("Corrupt or missing part: " + part["file"])
                dest.write(data)
        if encoded.stat().st_size != spec["transfer_size"] or sha256(encoded) != spec["transfer_sha256"]:
            raise RuntimeError("Corrupted concatenated transfer for " + spec["path"])
        temp_output = Path(directory) / "restored.original"
        if spec["transfer_encoding"] == "xz":
            with lzma.open(encoded, "rb") as src, temp_output.open("wb") as dest:
                shutil.copyfileobj(src, dest, length=1024 * 1024)
        elif spec["transfer_encoding"] == "raw":
            shutil.copyfile(encoded, temp_output)
        else:
            raise ValueError("Unsupported transfer encoding")
        if temp_output.stat().st_size != spec["size"] or sha256(temp_output) != spec["sha256"]:
            raise RuntimeError("Final SHA256 mismatch for " + spec["path"])
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".goldstation-", delete=False) as dest:
            staging = Path(dest.name)
            with temp_output.open("rb") as src:
                shutil.copyfileobj(src, dest)
        os.replace(staging, output)
    return "RESTORED " + spec["path"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--verify-only", action="store_true")
    args = p.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for spec in manifest["binary_files"]:
        print(restore_one(spec, check_only=args.verify_only), flush=True)
    print("ALL_BINARY_SHA256_OK")


if __name__ == "__main__":
    main()
