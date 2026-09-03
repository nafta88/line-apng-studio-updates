from pathlib import Path
import shutil
import subprocess
import tempfile

from engine import FRAME_CATALOG, FRAME_LAYOUTS, apng_info, render_package


def main():
    root = Path(tempfile.mkdtemp(prefix="line-apng-test-"))
    try:
        source = root / "sample.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", "testsrc2=size=640x360:rate=30", "-t", "18", "-pix_fmt", "yuv420p", str(source),
        ], check=True)
        assert len(FRAME_CATALOG) == 64
        from engine import LAYOUTS
        assert len(LAYOUTS) == 32
        required = {"OK！", "了解！", "ありがとう", "ごめんね", "おはよう！", "おやすみ", "おつかれさま", "今から帰る"}
        assert required.issubset({p["defaultText"] for p in FRAME_CATALOG.values()})
        themes = list(FRAME_CATALOG)[:8]
        layouts = [item["id"] for item in LAYOUTS[:8]]
        slots = [{"text": FRAME_CATALOG[themes[i]]["defaultText"], "start": i*2, "duration": 2, "focusX": .5, "focusY": .5, "zoom": 1, "theme": themes[i], "layout": layouts[i]} for i in range(8)]
        archive, report = render_package(source, {"slots": slots}, root)
        assert archive.exists() and len(report) == 8
        for i in range(1, 9):
            info = apng_info(root / "LINE_APNG_8" / f"{i:02d}.png")
            assert info["width"] == 320 and info["height"] == 270
            assert 5 <= info["frames"] <= 20
            assert info["bytes"] <= 1_000_000
        main_info = apng_info(root / "LINE_APNG_8" / "main.png")
        assert main_info["width"] == 240 and main_info["height"] == 240
        assert main_info["bytes"] <= 1_000_000
        from PIL import Image
        with Image.open(root / "LINE_APNG_8" / "tab.png") as tab:
            assert tab.size == (96, 74)
        print("PASS", archive, report)
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
