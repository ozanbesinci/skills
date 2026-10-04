"""Build a deterministic standalone skill.zip and verify every manifest entry."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

def sha(data):
    return hashlib.sha256(data).hexdigest()

def source_files(skill):
    result = {}
    for path in sorted(skill.rglob("*")):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError(f"Source link rejected: {path}")
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        result[path.relative_to(skill).as_posix()] = path.read_bytes()
    if "scripts/teklif-guncelle.py" in result or "scripts/teklif_paket_legacy.py" in result:
        raise ValueError("Removed offer installer returned")
    return result

def build_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo("guncelleyici/" + name, (2026, 10, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            package.writestr(info, data)
    return buffer.getvalue()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--refresh-manifest", action="store_true")
    args = parser.parse_args()
    skill = Path(__file__).resolve().parents[1] / "skills/guncelleyici"
    if args.out.resolve().is_relative_to(skill):
        raise ValueError("Release output must be outside the skill tree")
    version = (skill / "VERSION").read_text(encoding="utf-8-sig").strip()
    files = source_files(skill)
    manifest_name = "MANIFEST.sha256.json"
    records = {name: sha(data) for name, data in files.items() if name != manifest_name}
    if args.refresh_manifest:
        manifest = {"schema": "guncelleyici-source-manifest/v1", "version": version, "files": records}
        (skill / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        files = source_files(skill)
    manifest = json.loads(files[manifest_name])
    if manifest["version"] != version or manifest["files"] != records:
        raise ValueError("Source manifest mismatch")
    binary = build_bytes(files)
    if binary != build_bytes(files):
        raise ValueError("Archive is not deterministic")
    with zipfile.ZipFile(io.BytesIO(binary)) as package:
        if package.testzip() is not None:
            raise ValueError("Archive CRC failure")
        expected = {"guncelleyici/"+name: data for name, data in files.items()}
        if set(package.namelist()) != set(expected):
            raise ValueError("Archive member mismatch")
        for name, data in expected.items():
            if package.read(name) != data:
                raise ValueError(f"Archive bytes mismatch: {name}")
    args.out.mkdir(parents=True, exist_ok=True)
    archive = args.out / "skill.zip"
    archive.write_bytes(binary)
    digest = sha(binary)
    (args.out / "skill.zip.sha256").write_text(f"{digest}  skill.zip\n", encoding="ascii")
    print(json.dumps({"status": "PASS", "version": version, "files": len(files), "sha256": digest,
                      "deterministic": True, "manifest_verified": True}))

if __name__ == "__main__":
    main()
