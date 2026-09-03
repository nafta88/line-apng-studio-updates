from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

import updater


def make_package() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(updater.REQUIRED_UPDATE_FILES):
            archive.writestr(name, f"safe test file: {name}\n")
    return buffer.getvalue()


def main() -> None:
    assert updater.parse_version("1.2.3") == (1, 2, 3)
    for bad in ("1", "1.2", "v1.2.3", "1.2.x", "1.2.3.4"):
        try:
            updater.parse_version(bad)
        except updater.UpdateError:
            pass
        else:
            raise AssertionError(f"invalid version accepted: {bad}")

    package = make_package()
    assert len(package) < updater.MAX_PACKAGE_BYTES
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        entries = updater._safe_zip_entries(archive)
        assert len(entries) == len(updater.REQUIRED_UPDATE_FILES)

    bad_buffer = io.BytesIO()
    with zipfile.ZipFile(bad_buffer, "w") as archive:
        archive.writestr("../source.video", b"must never be accepted")
    try:
        with zipfile.ZipFile(io.BytesIO(bad_buffer.getvalue())) as archive:
            updater._safe_zip_entries(archive)
    except updater.UpdateError:
        pass
    else:
        raise AssertionError("unsafe zip entry accepted")

    private_key = os.environ.get("LINE_APNG_TEST_PRIVATE_KEY")
    if private_key:
        root = Path(tempfile.mkdtemp(prefix="line-apng-signature-test-"))
        try:
            package_url = updater.RELEASE_PREFIX + "line-apng-studio-0.5.1.zip"
            manifest = {
                "version": "0.5.1",
                "package_url": package_url,
                "sha256": hashlib.sha256(package).hexdigest(),
                "notes": "署名検査用",
            }
            payload = updater._signed_payload(manifest)
            payload_path = root / "payload.txt"
            signature_path = root / "signature.bin"
            payload_path.write_bytes(payload)
            subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", private_key, "-out", str(signature_path), str(payload_path)],
                check=True,
            )
            manifest["signature"] = base64.b64encode(signature_path.read_bytes()).decode("ascii")
            updater._verify_signature(manifest, root)
            manifest["sha256"] = "0" * 64
            try:
                updater._verify_signature(manifest, root)
            except updater.UpdateError:
                pass
            else:
                raise AssertionError("tampered signed data accepted")
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)
    print("PASS updater security")


if __name__ == "__main__":
    main()
