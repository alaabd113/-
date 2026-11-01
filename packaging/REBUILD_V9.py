#!/usr/bin/env python3
"""Rebuild GoldStation V9 from the four ZIP transport files after extracting them."""
from pathlib import Path
import hashlib, json, lzma, os, sys, zipfile

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def main():
    for entry in MANIFEST["chunks"]:
        p = ROOT / entry["name"]
        if not p.is_file() or p.stat().st_size != entry["bytes"] or sha256(p) != entry["sha256"]:
            raise SystemExit("Missing or invalid part: " + entry["name"])
    output = ROOT / MANIFEST["source_name"]
    tmp = ROOT / (MANIFEST["source_name"] + ".incomplete")
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    try:
        with tmp.open("wb") as dst:
            for entry in MANIFEST["chunks"]:
                with (ROOT / entry["name"]).open("rb") as src:
                    while True:
                        block = src.read(1024 * 1024)
                        if not block:
                            break
                        dst.write(decoder.decompress(block))
        if not decoder.eof or tmp.stat().st_size != MANIFEST["source_size_bytes"] or sha256(tmp) != MANIFEST["source_sha256"]:
            raise RuntimeError("Reconstructed archive failed SHA-256 verification")
        os.replace(tmp, output)
    finally:
        if tmp.exists():
            tmp.unlink()
    print("Verified:", output)
    if "--archive-only" in sys.argv:
        return
    target = ROOT / "GoldStation_V9_RESTORED"
    target.mkdir(exist_ok=True)
    base = target.resolve()
    with zipfile.ZipFile(output) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError("Bad member: " + bad)
        for member in z.infolist():
            destination = (target / member.filename).resolve()
            if os.path.commonpath([str(base), str(destination)]) != str(base):
                raise RuntimeError("Unsafe path in ZIP: " + member.filename)
        z.extractall(target)
        print("Restored", len(z.infolist()), "entries")

if __name__ == "__main__":
    main()
