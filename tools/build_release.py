from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    from updater import ALLOWED_UPDATE_FILES, REQUIRED_UPDATE_FILES, RELEASE_PREFIX
    from version import APP_VERSION

    if not args.private_key.is_file():
        raise SystemExit("Private signing key not found")
    if args.private_key.resolve().is_relative_to(ROOT):
        raise SystemExit("Private signing key must never be inside the repository")

    missing = [name for name in REQUIRED_UPDATE_FILES if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit(f"Missing release files: {missing}")

    args.output.mkdir(parents=True, exist_ok=True)
    package_name = f"line-apng-studio-{APP_VERSION}.zip"
    package_path = args.output / package_name
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(ALLOWED_UPDATE_FILES):
            source = ROOT / name
            if source.is_file():
                archive.write(source, name)

    with zipfile.ZipFile(package_path) as archive:
        names = {info.filename for info in archive.infolist() if not info.is_dir()}
        if not REQUIRED_UPDATE_FILES.issubset(names) or not names.issubset(ALLOWED_UPDATE_FILES):
            raise SystemExit("Release archive allowlist check failed")
        forbidden_suffixes = {".mp4", ".mov", ".m4v", ".apng", ".key"}
        if any(Path(name).suffix.lower() in forbidden_suffixes for name in names):
            raise SystemExit("Private media or key detected in release archive")
        if any("private" in name.lower() or "work/" in name.lower() for name in names):
            raise SystemExit("Private working data detected in release archive")

    encoded_name = package_name + ".b64"
    encoded_path = args.output / encoded_name
    encoded_path.write_text(base64.b64encode(package_path.read_bytes()).decode("ascii"), encoding="ascii")
    manifest = {
        "version": APP_VERSION,
        "package_url": RELEASE_PREFIX + encoded_name,
        "sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
        "notes": "32種類の輪郭、64種類の動く装飾、連動プレビュー、安全なローカル処理と署名付き自動更新に対応しました。",
    }
    from updater import _signed_payload
    openssl = shutil.which("openssl")
    if not openssl:
        raise SystemExit("openssl not found")
    temporary = Path(tempfile.mkdtemp(prefix="line-apng-release-sign-"))
    try:
        payload = temporary / "payload.json"
        signature = temporary / "signature.bin"
        payload.write_bytes(_signed_payload(manifest))
        subprocess.run(
            [openssl, "dgst", "-sha256", "-sign", str(args.private_key), "-out", str(signature), str(payload)],
            check=True,
        )
        manifest["signature"] = base64.b64encode(signature.read_bytes()).decode("ascii")
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    (args.output / "latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(package_path)
    print(args.output / "latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
