from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from updater import ALLOWED_UPDATE_FILES, REQUIRED_UPDATE_FILES


def wait_for_parent(pid: int, timeout: int = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(0.2)
    return False


def validate_paths(staging: Path, app_dir: Path) -> list[str]:
    if app_dir != Path(__file__).resolve().parent:
        raise RuntimeError("更新対象のアプリフォルダが一致しません。")
    if staging.parent.parent.name != "line-apng-studio-private":
        raise RuntimeError("更新データの保存場所が不正です。")
    names = {
        str(path.relative_to(staging))
        for path in staging.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if not REQUIRED_UPDATE_FILES.issubset(names) or not names.issubset(ALLOWED_UPDATE_FILES):
        raise RuntimeError("更新対象ファイルが許可リストと一致しません。")
    return sorted(names, key=lambda name: (name == "version.py", name))


def apply_update(staging: Path, app_dir: Path) -> None:
    names = validate_paths(staging, app_dir)
    backup = Path(tempfile.mkdtemp(prefix="line-apng-backup-"))
    backup.chmod(0o700)
    replaced = []
    try:
        for name in names:
            source = staging / name
            target = app_dir / name
            backup_target = backup / name
            backup_target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if target.exists():
                shutil.copy2(target, backup_target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.update")
            shutil.copy2(source, temporary)
            temporary.chmod(0o644)
            os.replace(temporary, target)
            replaced.append(name)
    except Exception:
        for name in reversed(replaced):
            target = app_dir / name
            saved = backup / name
            if saved.exists():
                shutil.copy2(saved, target)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(staging.parent, ignore_errors=True)


def restart(app_dir: Path) -> None:
    command = app_dir / "start.command"
    if sys.platform == "darwin" and command.is_file():
        subprocess.Popen(["/usr/bin/open", str(command)], close_fds=True, start_new_session=True)
    else:
        subprocess.Popen([sys.executable, str(app_dir / "app.py")], cwd=app_dir, close_fds=True, start_new_session=True)


def main() -> int:
    if len(sys.argv) != 4:
        return 2
    staging = Path(sys.argv[1]).resolve()
    app_dir = Path(sys.argv[2]).resolve()
    parent_pid = int(sys.argv[3])
    if not wait_for_parent(parent_pid):
        return 3
    apply_update(staging, app_dir)
    restart(app_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
