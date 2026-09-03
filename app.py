from __future__ import annotations

import atexit
import fcntl
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file
from waitress import create_server

from engine import RenderError, create_browser_preview, render_package
from updater import UpdateError, check_for_update, prepare_update
from version import APP_VERSION

BASE_DIR = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765
ORIGIN = f"http://{HOST}:{PORT}"
SESSION_TOKEN = secrets.token_urlsafe(32)
SESSION_BASE = f"/s/{SESSION_TOKEN}"
PRIVATE_ROOT = Path(tempfile.gettempdir()) / "line-apng-studio-private"
WORK_DIR: Path | None = None
_LOCK_HANDLE = None
_SERVER = None
_UPDATE_LOCK = threading.Lock()

app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=2 * 1024 * 1024 * 1024,
    MAX_FORM_MEMORY_SIZE=2 * 1024 * 1024,
    SEND_FILE_MAX_AGE_DEFAULT=0,
)


def ensure_private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def create_private_work_dir() -> Path:
    ensure_private_directory(PRIVATE_ROOT)
    path = Path(tempfile.mkdtemp(prefix="run-", dir=PRIVATE_ROOT))
    path.chmod(0o700)
    return path


def clean_abandoned_runs() -> None:
    """Only called while holding the single-instance lock."""
    ensure_private_directory(PRIVATE_ROOT)
    for item in PRIVATE_ROOT.glob("run-*"):
        try:
            shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink(missing_ok=True)
        except OSError:
            pass


def acquire_single_instance_lock():
    global _LOCK_HANDLE
    ensure_private_directory(PRIVATE_ROOT)
    handle = (PRIVATE_ROOT / "app.lock").open("a+")
    os.chmod(handle.name, 0o600)
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return False
    _LOCK_HANDLE = handle
    return True


def active_work_dir() -> Path:
    if WORK_DIR is None:
        raise RuntimeError("アプリの安全な作業領域を準備できませんでした。")
    return WORK_DIR


@app.before_request
def restrict_request_boundary():
    # Exact Host matching prevents DNS-rebinding access to this local service.
    if request.host != f"{HOST}:{PORT}":
        abort(403)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("Origin")
        if origin and origin != ORIGIN:
            abort(403)


@app.after_request
def security_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "local-network=(self), loopback-network=(self)"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
        "style-src 'self'; script-src 'self'; connect-src 'self'"
    )
    return response


@app.get(f"{SESSION_BASE}/")
def index():
    return render_template("index.html", session_base=SESSION_BASE, app_version=APP_VERSION)


def resolve_job(job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
        raise RenderError("動画の処理情報が無効です。動画を選び直してください。")
    job_dir = active_work_dir() / f"job-{job_id}"
    if not job_dir.is_dir():
        raise RenderError("選択した動画の一時データが見つかりません。動画を選び直してください。")
    return job_dir


@app.post(f"{SESSION_BASE}/prepare")
def prepare():
    video = request.files.get("video")
    if not video or not video.filename:
        return jsonify(error="動画を選択してください。"), 400
    job_id = uuid.uuid4().hex
    job_dir = active_work_dir() / f"job-{job_id}"
    job_dir.mkdir(parents=True, mode=0o700)
    job_dir.chmod(0o700)
    source = job_dir / "source.video"
    preview = job_dir / "preview.mp4"
    try:
        video.save(source)
        info = create_browser_preview(source, preview)
        os.chmod(source, 0o600)
        os.chmod(preview, 0o600)
        return jsonify(jobId=job_id, duration=info["duration"], width=info["width"], height=info["height"], previewUrl=f"{SESSION_BASE}/preview/{job_id}")
    except RenderError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify(error=str(exc)), 400
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        app.logger.exception("Local video preparation failed")
        return jsonify(error="動画の読み込みに失敗しました。動画を選び直してください。"), 500


@app.get(f"{SESSION_BASE}/preview/<job_id>")
def preview(job_id: str):
    try:
        job_dir = resolve_job(job_id)
        return send_file(job_dir / "preview.mp4", mimetype="video/mp4", conditional=True)
    except RenderError as exc:
        return jsonify(error=str(exc)), 404


@app.post(f"{SESSION_BASE}/render")
def render():
    job_id = request.form.get("jobId", "")
    raw_config = request.form.get("config", "")
    try:
        config = json.loads(raw_config)
    except json.JSONDecodeError:
        return jsonify(error="設定データが壊れています。"), 400
    try:
        job_dir = resolve_job(job_id)
        source = job_dir / "source.video"
        package_path, report = render_package(source, config, job_dir)
        response = send_file(
            package_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name="LINE_APNG_8.zip",
        )
        response.headers["X-Render-Report"] = json.dumps(report, ensure_ascii=True)
        return response
    except RenderError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        app.logger.exception("Local APNG rendering failed")
        return jsonify(error="処理に失敗しました。設定を確認してもう一度お試しください。"), 500


@app.post(f"{SESSION_BASE}/update/check")
def update_check():
    try:
        return jsonify(check_for_update(PRIVATE_ROOT))
    except UpdateError as exc:
        return jsonify(error=str(exc)), 400


def shutdown_for_update() -> None:
    remove_work_dir()
    if _SERVER is not None:
        _SERVER.close()
    os._exit(0)


@app.post(f"{SESSION_BASE}/update/install")
def update_install():
    if not _UPDATE_LOCK.acquire(blocking=False):
        return jsonify(error="更新処理はすでに開始しています。"), 409
    try:
        staging, manifest = prepare_update(PRIVATE_ROOT)
        log_path = PRIVATE_ROOT / "update.log"
        log_handle = log_path.open("ab")
        os.chmod(log_path, 0o600)
        subprocess.Popen(
            [sys.executable, str(BASE_DIR / "update_helper.py"), str(staging), str(BASE_DIR), str(os.getpid())],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            close_fds=True,
            start_new_session=True,
        )
        log_handle.close()
        threading.Timer(1.0, shutdown_for_update).start()
        return jsonify(ok=True, version=manifest["version"], message="署名を確認しました。安全に再起動して更新します。")
    except UpdateError as exc:
        _UPDATE_LOCK.release()
        return jsonify(error=str(exc)), 400
    except Exception:
        _UPDATE_LOCK.release()
        app.logger.exception("Secure update launch failed")
        return jsonify(error="更新を開始できませんでした。現在のアプリは変更されていません。"), 500


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="動画が2GBを超えています。短くしてから選択してください。"), 413


def remove_work_dir() -> None:
    if WORK_DIR is not None:
        shutil.rmtree(WORK_DIR, ignore_errors=True)


def run_local_app() -> int:
    global WORK_DIR, _SERVER
    os.umask(0o077)
    if not acquire_single_instance_lock():
        try:
            existing_url = (PRIVATE_ROOT / "current-url").read_text(encoding="utf-8").strip()
            if existing_url.startswith(f"{ORIGIN}/s/"):
                webbrowser.open(existing_url)
        except OSError:
            pass
        print("LINE APNG Studioはすでに起動しています。")
        return 0

    clean_abandoned_runs()
    WORK_DIR = create_private_work_dir()
    url = f"{ORIGIN}{SESSION_BASE}/"
    current_url = PRIVATE_ROOT / "current-url"
    current_url.write_text(url, encoding="utf-8")
    current_url.chmod(0o600)
    atexit.register(remove_work_dir)

    _SERVER = create_server(
        app,
        host=HOST,
        port=PORT,
        threads=4,
        channel_timeout=30,
        clear_untrusted_proxy_headers=True,
    )
    if os.environ.get("LINE_APNG_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"LINE APNG Studio: {url}")
    print("終了するにはこのウインドウで control + C を押してください。")
    try:
        _SERVER.run()
    except KeyboardInterrupt:
        pass
    finally:
        _SERVER.close()
        remove_work_dir()
        current_url.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_local_app())
