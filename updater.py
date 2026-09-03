from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from version import APP_VERSION

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_KEY = BASE_DIR / "update_public.pem"
REPOSITORY = "nafta88/line-apng-studio-updates"
RELEASE_PREFIX = f"https://raw.githubusercontent.com/{REPOSITORY}/main/releases/"
MANIFEST_URL = f"{RELEASE_PREFIX}latest.json"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_PACKAGE_BYTES = 25 * 1024 * 1024
MAX_EXTRACTED_BYTES = 60 * 1024 * 1024

# Updates may replace only generic program files. Videos, work data, virtual
# environments, settings, keys and generated APNG files are never accepted.
ALLOWED_UPDATE_FILES = {
    "app.py",
    "engine.py",
    "updater.py",
    "update_helper.py",
    "version.py",
    "update_public.pem",
    "README.md",
    "static/app.js",
    "static/style.css",
    "static/frame_catalog.json",
    "templates/index.html",
}
REQUIRED_UPDATE_FILES = ALLOWED_UPDATE_FILES - {"README.md"}


class UpdateError(RuntimeError):
    pass


def parse_version(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise UpdateError("更新情報のバージョン表記が不正です。")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def _validate_release_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "raw.githubusercontent.com":
        raise UpdateError("更新先が許可されたGitHubではありません。")
    expected_path = f"/{REPOSITORY}/main/releases/"
    decoded_path = urllib.parse.unquote(parsed.path)
    path = PurePosixPath(decoded_path)
    if not decoded_path.startswith(expected_path) or ".." in path.parts:
        raise UpdateError("更新先リポジトリが一致しません。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise UpdateError("更新先URLに許可されていない情報があります。")


class _NoUnexpectedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_release_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, limit: int) -> bytes:
    _validate_release_url(url)
    opener = urllib.request.build_opener(_NoUnexpectedRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": f"LINE-APNG-Studio/{APP_VERSION}"})
    try:
        with opener.open(request, timeout=12) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > limit:
                raise UpdateError("更新ファイルが安全上の上限を超えています。")
            data = response.read(limit + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise UpdateError("GitHubから更新情報を取得できませんでした。") from exc
    if len(data) > limit:
        raise UpdateError("更新ファイルが安全上の上限を超えています。")
    return data


def _signed_payload(manifest: dict) -> bytes:
    protected = {
        "notes": manifest["notes"],
        "package_url": manifest["package_url"],
        "sha256": manifest["sha256"],
        "version": manifest["version"],
    }
    return json.dumps(protected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verify_signature(manifest: dict, private_root: Path) -> None:
    try:
        signature = base64.b64decode(manifest["signature"], validate=True)
    except (KeyError, ValueError) as exc:
        raise UpdateError("更新情報の電子署名が不正です。") from exc
    if not PUBLIC_KEY.is_file() or PUBLIC_KEY.stat().st_size > 16 * 1024:
        raise UpdateError("更新確認用の公開鍵が見つかりません。")
    openssl = shutil.which("openssl")
    if not openssl:
        raise UpdateError("macOSの署名確認機能が見つかりません。")
    verify_dir = Path(tempfile.mkdtemp(prefix="verify-", dir=private_root))
    try:
        payload_path = verify_dir / "payload.txt"
        signature_path = verify_dir / "signature.bin"
        payload_path.write_bytes(_signed_payload(manifest))
        signature_path.write_bytes(signature)
        os.chmod(payload_path, 0o600)
        os.chmod(signature_path, 0o600)
        result = subprocess.run(
            [openssl, "dgst", "-sha256", "-verify", str(PUBLIC_KEY), "-signature", str(signature_path), str(payload_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise UpdateError("電子署名が一致しないため、更新を拒否しました。")
    finally:
        shutil.rmtree(verify_dir, ignore_errors=True)


def fetch_manifest(private_root: Path) -> dict:
    try:
        manifest = json.loads(_download(MANIFEST_URL, MAX_MANIFEST_BYTES))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpdateError("更新情報を読み取れませんでした。") from exc
    if not isinstance(manifest, dict):
        raise UpdateError("更新情報の形式が不正です。")
    required = {"version", "package_url", "sha256", "signature", "notes"}
    if set(manifest) != required or any(not isinstance(manifest[key], str) for key in required):
        raise UpdateError("更新情報に不正な項目があります。")
    parse_version(manifest["version"])
    _validate_release_url(manifest["package_url"])
    if len(manifest["notes"]) > 500 or len(manifest["sha256"]) != 64:
        raise UpdateError("更新情報の内容が不正です。")
    if any(char not in "0123456789abcdef" for char in manifest["sha256"]):
        raise UpdateError("更新ファイルの識別情報が不正です。")
    _verify_signature(manifest, private_root)
    return manifest


def check_for_update(private_root: Path) -> dict:
    manifest = fetch_manifest(private_root)
    return {
        "currentVersion": APP_VERSION,
        "latestVersion": manifest["version"],
        "available": parse_version(manifest["version"]) > parse_version(APP_VERSION),
        "notes": manifest["notes"],
    }


def _safe_zip_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    files = []
    total = 0
    seen = set()
    for info in archive.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or str(path) not in ALLOWED_UPDATE_FILES:
            raise UpdateError("更新ZIPに許可されていないファイルがあります。")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode) or str(path) in seen:
            raise UpdateError("更新ZIPのファイル構造が不正です。")
        total += info.file_size
        if total > MAX_EXTRACTED_BYTES:
            raise UpdateError("展開後の更新サイズが安全上の上限を超えています。")
        seen.add(str(path))
        files.append(info)
    if not REQUIRED_UPDATE_FILES.issubset(seen):
        raise UpdateError("更新ZIPに必要なプログラムが不足しています。")
    return files


def prepare_update(private_root: Path) -> tuple[Path, dict]:
    manifest = fetch_manifest(private_root)
    if parse_version(manifest["version"]) <= parse_version(APP_VERSION):
        raise UpdateError("現在のバージョンが最新です。")
    encoded_package = _download(manifest["package_url"], MAX_PACKAGE_BYTES * 2)
    try:
        package = base64.b64decode(encoded_package, validate=True)
    except ValueError as exc:
        raise UpdateError("更新ファイルの符号化が不正です。") from exc
    if len(package) > MAX_PACKAGE_BYTES:
        raise UpdateError("更新ファイルが安全上の上限を超えています。")
    actual_hash = hashlib.sha256(package).hexdigest()
    if actual_hash != manifest["sha256"]:
        raise UpdateError("更新ファイルが改変されているため拒否しました。")
    update_dir = Path(tempfile.mkdtemp(prefix="update-", dir=private_root))
    update_dir.chmod(0o700)
    archive_path = update_dir / "package.zip"
    archive_path.write_bytes(package)
    os.chmod(archive_path, 0o600)
    staging = update_dir / "staging"
    staging.mkdir(mode=0o700)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = _safe_zip_entries(archive)
            for info in entries:
                destination = staging / info.filename
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with archive.open(info) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                destination.chmod(0o600)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(update_dir, ignore_errors=True)
        raise UpdateError("更新ZIPを安全に展開できませんでした。") from exc
    archive_path.unlink(missing_ok=True)
    return staging, manifest
