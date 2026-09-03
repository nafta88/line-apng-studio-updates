from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

CANVAS = (320, 270)
MAX_BYTES = 1_000_000
DEFAULT_TEXTS = [
    "おはよう！", "いってらっしゃい", "OK！", "ありがとう",
    "おつかれさま", "やったー！", "ごめんね", "おやすみ",
]
CATALOG_PATH = Path(__file__).resolve().parent / "static" / "frame_catalog.json"
FRAME_CATALOG = {item["id"]: item for item in json.loads(CATALOG_PATH.read_text(encoding="utf-8"))}
DEFAULT_FRAME = next(iter(FRAME_CATALOG.values()))
LAYOUTS = [
    {"id": "wide", "box": (12, 12, 308, 224)},
    {"id": "circle", "box": (51, 5, 269, 223)},
    {"id": "portrait", "box": (77, 4, 243, 224)},
    {"id": "arch", "box": (55, 4, 265, 224)},
    {"id": "heart", "box": (45, 2, 275, 224)},
    {"id": "star", "box": (48, 1, 272, 225)},
    {"id": "oval", "box": (30, 15, 290, 215)},
    {"id": "polaroid", "box": (42, 10, 278, 207)},
    {"id": "speech", "box": (28, 7, 292, 213)},
    {"id": "scallop", "box": (25, 8, 295, 218)},
    {"id": "diamond", "box": (57, 2, 263, 224)},
    {"id": "hex", "box": (38, 7, 282, 218)},
    {"id": "film", "box": (18, 31, 302, 205)},
    {"id": "phone", "box": (91, 3, 229, 224)},
    {"id": "badge", "box": (49, 3, 271, 224)},
    {"id": "wave", "box": (20, 15, 300, 215)},
    {"id": "capsule", "box": (22, 42, 298, 192)},
    {"id": "vertical_oval", "box": (82, 2, 238, 224)},
    {"id": "shield", "box": (59, 2, 261, 224)},
    {"id": "clover", "box": (48, 2, 272, 224)},
    {"id": "octagon", "box": (43, 4, 277, 224)},
    {"id": "ticket", "box": (20, 30, 300, 204)},
    {"id": "book", "box": (28, 13, 292, 216)},
    {"id": "cloud", "box": (27, 14, 293, 214)},
    {"id": "burst", "box": (43, 1, 277, 225)},
    {"id": "drop", "box": (69, 1, 251, 224)},
    {"id": "egg", "box": (74, 1, 246, 224)},
    {"id": "trapezoid", "box": (37, 12, 283, 218)},
    {"id": "tv", "box": (25, 20, 295, 207)},
    {"id": "stamp", "box": (50, 2, 270, 224)},
    {"id": "flower_shape", "box": (48, 2, 272, 224)},
    {"id": "leaf_shape", "box": (49, 2, 271, 224)},
]
FRAME_LAYOUTS = {key: LAYOUTS[i % len(LAYOUTS)] for i, key in enumerate(FRAME_CATALOG)}
LAYOUT_BY_ID = {layout["id"]: layout for layout in LAYOUTS}


class RenderError(RuntimeError):
    pass


def run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RenderError("FFmpegが見つかりません。setup.commandを実行してください。") from exc
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or "").strip().splitlines()
        raise RenderError(f"動画処理に失敗しました: {message[-1] if message else '不明なエラー'}") from exc


def probe_video(source: Path) -> dict:
    result = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration", "-of", "json", str(source),
    ])
    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise RenderError("動画トラックを読み取れませんでした。")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise RenderError("動画の長さを取得できませんでした。")
    return {"duration": duration, **data["streams"][0]}


def create_browser_preview(source: Path, destination: Path) -> dict:
    """ブラウザ互換性に左右されない、低負荷のローカルプレビューを作る。"""
    info = probe_video(source)
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-vf", "scale=960:-2:force_original_aspect_ratio=decrease",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(destination),
    ])
    return info


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def extract_frames(source: Path, slot: dict, count: int, dest: Path) -> list[Path]:
    start = max(0.0, float(slot.get("start", 0)))
    duration = int(slot.get("duration", 2))
    focus_x = min(1.0, max(0.0, float(slot.get("focusX", 0.5))))
    focus_y = min(1.0, max(0.0, float(slot.get("focusY", 0.5))))
    zoom = min(2.2, max(1.0, float(slot.get("zoom", 1.0))))
    fps = count / duration
    theme = str(slot.get("theme") or "")
    layout = LAYOUT_BY_ID.get(str(slot.get("layout") or ""), FRAME_LAYOUTS.get(theme, LAYOUTS[0]))
    box = layout["box"]
    w, h = box[2] - box[0], box[3] - box[1]
    sw, sh = max(w, round(w * zoom)), max(h, round(h * zoom))
    vf = (
        f"fps={fps:.6f},"
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}:(iw-{w})*{focus_x:.5f}:(ih-{h})*{focus_y:.5f},"
        "format=rgba"
    )
    dest.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}",
        "-i", str(source), "-t", str(duration), "-vf", vf, "-frames:v", str(count),
        str(dest / "%03d.png"),
    ])
    frames = sorted(dest.glob("*.png"))
    if len(frames) < 5:
        raise RenderError("指定区間から5フレーム以上を取得できません。開始位置を早めてください。")
    return frames[:count]


def layout_mask(layout_id: str, size: tuple[int, int]) -> Image.Image:
    w, h = size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    if layout_id in {"circle", "oval", "vertical_oval"}:
        draw.ellipse((1, 1, w - 2, h - 2), fill=255)
    elif layout_id == "portrait" or layout_id == "phone":
        draw.rounded_rectangle((1, 1, w - 2, h - 2), radius=min(w, h) // 3, fill=255)
    elif layout_id == "arch":
        draw.ellipse((1, 1, w - 2, h * .9), fill=255)
        draw.rectangle((1, h * .42, w - 2, h - 2), fill=255)
    elif layout_id == "heart":
        points = []
        for n in range(160):
            t = math.tau * n / 160
            x = 16 * math.sin(t) ** 3
            y = 13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t)
            points.append((w/2 + x*w/35, h*.48 - y*h/32))
        draw.polygon(points, fill=255)
    elif layout_id == "star":
        draw.polygon(star_points(w/2, h/2, min(w, h)*.49, min(w, h)*.26, -math.pi/2), fill=255)
    elif layout_id == "speech":
        draw.rounded_rectangle((1, 1, w - 2, h * .86), radius=35, fill=255)
        draw.polygon([(w*.62, h*.78), (w*.82, h*.98), (w*.77, h*.72)], fill=255)
    elif layout_id == "scallop":
        draw.rounded_rectangle((10, 10, w-11, h-11), radius=36, fill=255)
        for x in range(18, w, 36):
            draw.ellipse((x-19, -1, x+19, 37), fill=255)
            draw.ellipse((x-19, h-38, x+19, h), fill=255)
        for y in range(18, h, 36):
            draw.ellipse((-1, y-19, 37, y+19), fill=255)
            draw.ellipse((w-38, y-19, w, y+19), fill=255)
    elif layout_id == "diamond":
        draw.polygon([(w/2, 1), (w-2, h/2), (w/2, h-2), (1, h/2)], fill=255)
    elif layout_id == "hex":
        draw.polygon([(w*.24,1),(w*.76,1),(w-2,h/2),(w*.76,h-2),(w*.24,h-2),(1,h/2)], fill=255)
    elif layout_id == "badge":
        draw.ellipse((1, 1, w-2, h*.82), fill=255)
        draw.polygon([(w*.16,h*.48),(w*.84,h*.48),(w*.72,h*.9),(w/2,h-2),(w*.28,h*.9)], fill=255)
    elif layout_id == "wave":
        top = [(x, 10 + math.sin(x/w*math.tau*2)*9) for x in range(w)]
        bottom = [(x, h-11 + math.sin(x/w*math.tau*2 + math.pi)*9) for x in reversed(range(w))]
        draw.polygon(top + bottom, fill=255)
    elif layout_id == "shield":
        draw.polygon([(1,1),(w-2,1),(w*.88,h*.66),(w/2,h-2),(w*.12,h*.66)], fill=255)
        draw.ellipse((1, -h*.18, w-2, h*.45), fill=255)
    elif layout_id == "clover":
        for cx, cy in [(w*.34,h*.32),(w*.66,h*.32),(w*.34,h*.66),(w*.66,h*.66)]:
            draw.ellipse((cx-w*.28,cy-h*.28,cx+w*.28,cy+h*.28),fill=255)
    elif layout_id == "octagon":
        draw.polygon([(w*.28,1),(w*.72,1),(w-2,h*.28),(w-2,h*.72),(w*.72,h-2),(w*.28,h-2),(1,h*.72),(1,h*.28)],fill=255)
    elif layout_id == "ticket":
        draw.rounded_rectangle((1,1,w-2,h-2),radius=18,fill=255)
        for y in (h*.33,h*.67):
            draw.ellipse((-10,y-10,10,y+10),fill=0);draw.ellipse((w-11,y-10,w+9,y+10),fill=0)
    elif layout_id == "book":
        draw.polygon([(1,h*.08),(w*.48,h*.02),(w/2,h*.13),(w*.52,h*.02),(w-2,h*.08),(w*.94,h*.96),(w*.52,h*.84),(w/2,h*.95),(w*.48,h*.84),(w*.06,h*.96)],fill=255)
    elif layout_id == "cloud":
        draw.rounded_rectangle((w*.06,h*.3,w*.94,h*.88),radius=35,fill=255)
        for cx,cy,r in [(w*.24,h*.38,w*.2),(w*.48,h*.25,w*.27),(w*.74,h*.38,w*.21)]:
            draw.ellipse((cx-r,cy-r,cx+r,cy+r),fill=255)
    elif layout_id == "burst":
        points=[]
        for n in range(32):
            r=min(w,h)*(.49 if n%2==0 else .34);a=-math.pi/2+n*math.pi/16
            points.append((w/2+math.cos(a)*r,h/2+math.sin(a)*r))
        draw.polygon(points,fill=255)
    elif layout_id == "drop":
        right=[(w/2+w*.46*math.sin(math.pi*t),h*(.02+.96*t)) for t in [n/50 for n in range(51)]]
        left=[(w/2-w*.46*math.sin(math.pi*t),h*(.02+.96*t)) for t in [n/50 for n in reversed(range(51))]]
        points=right+left
        draw.polygon(points,fill=255)
    elif layout_id == "egg":
        right=[]
        for n in range(61):
            t=n/60;half=w*math.sin(math.pi*t)*(.28+.2*t)
            right.append((w/2+half,h*(.01+.98*t)))
        left=[(w-(x),y) for x,y in reversed(right)]
        draw.polygon(right+left,fill=255)
    elif layout_id == "trapezoid":
        draw.polygon([(w*.18,1),(w*.82,1),(w-2,h-2),(1,h-2)],fill=255)
    elif layout_id == "tv":
        draw.rounded_rectangle((1,1,w-2,h*.86),radius=28,fill=255)
        draw.polygon([(w*.37,h*.82),(w*.63,h*.82),(w*.72,h-2),(w*.28,h-2)],fill=255)
    elif layout_id == "stamp":
        draw.rectangle((10,10,w-11,h-11),fill=255)
        for x in range(10,w,22):
            draw.ellipse((x-8,-1,x+8,15),fill=255);draw.ellipse((x-8,h-16,x+8,h),fill=255)
        for y in range(10,h,22):
            draw.ellipse((-1,y-8,15,y+8),fill=255);draw.ellipse((w-16,y-8,w,y+8),fill=255)
    elif layout_id == "flower_shape":
        for n in range(8):
            a=n*math.tau/8;cx=w/2+math.cos(a)*w*.22;cy=h/2+math.sin(a)*h*.22
            draw.ellipse((cx-w*.24,cy-h*.24,cx+w*.24,cy+h*.24),fill=255)
        draw.ellipse((w*.23,h*.23,w*.77,h*.77),fill=255)
    elif layout_id == "leaf_shape":
        upper=[(w*.01+w*.98*t,h/2-math.sin(math.pi*t)*h*.47) for t in [n/60 for n in range(61)]]
        lower=[(w*.01+w*.98*t,h/2+math.sin(math.pi*t)*h*.47) for t in [n/60 for n in reversed(range(61))]]
        draw.polygon(upper+lower,fill=255)
    else:
        radius = h//2 if layout_id == "capsule" else 9 if layout_id in {"polaroid", "film"} else 25
        draw.rounded_rectangle((1, 1, w - 2, h - 2), radius=radius, fill=255)
    return mask


def star_points(cx: float, cy: float, outer: float, inner: float, rotation: float) -> list[tuple[float, float]]:
    points = []
    for n in range(10):
        radius = outer if n % 2 == 0 else inner
        angle = rotation + n * math.pi / 5
        points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return points


def hex_color(value: str, alpha: int = 245) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


def draw_heart(draw: ImageDraw.ImageDraw, x: float, y: float, r: float, color) -> None:
    draw.ellipse((x-r, y-r, x, y), fill=color)
    draw.ellipse((x, y-r, x+r, y), fill=color)
    draw.polygon([(x-r, y-r/3), (x+r, y-r/3), (x, y+r*1.45)], fill=color)


def draw_paw(draw: ImageDraw.ImageDraw, x: float, y: float, r: float, color) -> None:
    draw.ellipse((x-r, y-r*.3, x+r, y+r*1.25), fill=color)
    for dx, dy in [(-1.1, -1), (-.35, -1.45), (.45, -1.4), (1.15, -.85)]:
        draw.ellipse((x+dx*r-r*.38, y+dy*r-r*.45, x+dx*r+r*.38, y+dy*r+r*.45), fill=color)


def draw_effect(draw: ImageDraw.ImageDraw, theme: str, index: int, total: int) -> None:
    preset = FRAME_CATALOG.get(theme, DEFAULT_FRAME)
    effect = preset["effect"]
    primary = hex_color(preset["primary"])
    secondary = hex_color(preset["secondary"])
    phase = index / max(1, total)
    positions = [(18, 24), (302, 28), (22, 190), (296, 184), (72, 12), (248, 14)]

    if effect in {"heart", "heartshower", "lace"}:
        for n, (x, y) in enumerate(positions):
            bob = math.sin((phase + n / 6) * math.tau) * (9 if effect == "heartshower" else 5)
            draw_heart(draw, x, y + bob, 5 + n % 3, primary if n % 2 else secondary)
    elif effect in {"confetti", "party", "pixel", "candy"}:
        for n in range(16):
            x = 8 + ((n * 47 + index * (13 if effect == "party" else 8)) % 304)
            y = 4 + ((n * 31 + index * 15) % 214)
            size = 5 if effect == "pixel" else 4 + n % 4
            draw.rounded_rectangle((x, y, x + size, y + (size if effect == "pixel" else 11)), radius=1, fill=primary if n % 2 else secondary)
    elif effect in {"bubble", "water", "snow"}:
        for n in range(12):
            x = 10 + ((n * 61) % 302)
            y = 208 - ((n * 29 + index * 13) % 205)
            r = 3 + (n % 4) * 2
            if effect == "snow":
                draw.line((x-r, y, x+r, y), fill=secondary, width=2)
                draw.line((x, y-r, x, y+r), fill=secondary, width=2)
                draw.line((x-r*.7, y-r*.7, x+r*.7, y+r*.7), fill=primary, width=2)
            else:
                draw.ellipse((x-r, y-r, x+r, y+r), outline=primary if n % 2 else secondary, width=3)
    elif effect in {"petals", "flower", "leaf"}:
        for n in range(12):
            x = 12 + ((n * 53 + index * 7) % 296)
            y = 8 + ((n * 37 + index * 12) % 200)
            r = 4 + n % 3
            color = primary if n % 2 else secondary
            if effect == "flower":
                for a in range(0, 360, 72):
                    dx, dy = math.cos(math.radians(a)) * r, math.sin(math.radians(a)) * r
                    draw.ellipse((x+dx-r*.55, y+dy-r*.55, x+dx+r*.55, y+dy+r*.55), fill=color)
                draw.ellipse((x-2, y-2, x+2, y+2), fill=(255, 210, 60, 255))
            else:
                draw.ellipse((x-r, y-r*1.7, x+r, y+r*1.7), fill=color)
    elif effect == "paw":
        for n, (x, y) in enumerate(positions):
            draw_paw(draw, x, y + math.sin((phase+n/6)*math.tau)*5, 4.5, primary if n % 2 else secondary)
    elif effect in {"sparkle", "starburst", "fireworks", "orbit", "comic"}:
        for n, (x, y) in enumerate(positions):
            pulse = .55 + .45 * math.sin((phase + n / 6) * math.tau)
            r = 5 + 7 * pulse
            draw.polygon(star_points(x, y, r, r * (.22 if effect in {"starburst", "comic"} else .45), -math.pi/2 + phase*math.tau), fill=primary if n % 2 else secondary)
        if effect in {"fireworks", "comic"}:
            for n in range(10):
                angle = n * math.tau / 10 + phase
                draw.line((160+math.cos(angle)*92, 108+math.sin(angle)*70, 160+math.cos(angle)*120, 108+math.sin(angle)*93), fill=secondary, width=3)
    elif effect == "music":
        music_font = font(27)
        for n, (x, y) in enumerate(positions):
            draw.text((x-7, y-12 + math.sin((phase+n/6)*math.tau)*5), "♪" if n % 2 else "♫", font=music_font, fill=primary if n % 2 else secondary)
    else:
        for n, (x, y) in enumerate(positions):
            bob = math.sin((phase + n/6) * math.tau) * 6
            draw.ellipse((x-6, y+bob-6, x+6, y+bob+6), fill=primary if n % 2 else secondary)

    # 上部の象徴的な飾り。人物の顔を隠さない位置に固定する。
    if effect == "crown":
        draw.polygon([(128, 20), (140, 5), (151, 18), (160, 3), (171, 18), (182, 5), (192, 20), (188, 32), (132, 32)], fill=secondary, outline=primary)
    elif effect in {"bunny", "cat", "bear"}:
        if effect == "bunny":
            draw.ellipse((130, 0, 148, 42), fill=secondary, outline=primary, width=3); draw.ellipse((172, 0, 190, 42), fill=secondary, outline=primary, width=3)
        elif effect == "cat":
            draw.polygon([(126, 30), (138, 4), (153, 30)], fill=secondary, outline=primary); draw.polygon([(167, 30), (182, 4), (194, 30)], fill=secondary, outline=primary)
        else:
            draw.ellipse((128, 3, 153, 30), fill=secondary, outline=primary, width=3); draw.ellipse((167, 3, 192, 30), fill=secondary, outline=primary, width=3)
    elif effect == "ribbon":
        draw.ellipse((143, 4, 177, 30), outline=primary, width=5); draw.polygon([(145, 24), (125, 40), (150, 38)], fill=secondary); draw.polygon([(175, 24), (195, 40), (170, 38)], fill=secondary)
    elif effect == "angel":
        draw.arc((130, 1, 190, 23), 0, 360, fill=secondary, width=5); draw.arc((105, 20, 158, 76), 180, 350, fill=primary, width=5); draw.arc((162, 20, 215, 76), 190, 360, fill=primary, width=5)
    elif effect == "rainbow":
        for n, color in enumerate([(255,91,104,255),(255,175,62,255),(255,226,74,255),(73,199,112,255),(61,156,255,255),(143,99,220,255)]):
            draw.arc((108+n*3, -12+n*3, 212-n*3, 72-n*3), 180, 360, fill=color, width=4)
    elif effect == "cloud":
        for x, y, r in [(136,18,18),(158,10,24),(184,19,18)]: draw.ellipse((x-r,y-r,x+r,y+r),fill=secondary,outline=primary,width=2)
    elif effect == "moon":
        draw.ellipse((139, 2, 181, 44), fill=secondary); draw.ellipse((153, -2, 188, 34), fill=(0,0,0,0))
    elif effect == "sun":
        draw.ellipse((143, 4, 177, 38), fill=secondary, outline=primary, width=3)
        for n in range(8):
            a=n*math.tau/8+phase*.2; draw.line((160+math.cos(a)*23,21+math.sin(a)*23,160+math.cos(a)*34,21+math.sin(a)*34),fill=primary,width=3)
    elif effect == "balloon":
        for n, x in enumerate([36, 280]):
            y=48+math.sin((phase+n/2)*math.tau)*9; draw.ellipse((x-12,y-16,x+12,y+16),fill=primary if n else secondary); draw.line((x,y+16,x-4,y+50),fill=primary,width=2)
    elif effect == "cozy":
        draw.arc((125, 2, 195, 45), 200, 340, fill=secondary, width=7)


def fit_text(text: str, max_width: int) -> ImageFont.ImageFont:
    for size in range(38, 17, -2):
        chosen = font(size)
        box = chosen.getbbox(text)
        if box[2] - box[0] <= max_width:
            return chosen
    return font(18)


def compose(raw: Image.Image, text: str, theme: str, index: int, total: int, layout_id: str | None = None) -> Image.Image:
    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    layout = LAYOUT_BY_ID.get(layout_id or "", FRAME_LAYOUTS.get(theme, LAYOUTS[0]))
    box = layout["box"]
    w, h = box[2] - box[0], box[3] - box[1]
    local_mask = layout_mask(layout["id"], (w, h))
    full_mask = Image.new("L", CANVAS, 0)
    full_mask.paste(local_mask, (box[0], box[1]))
    border_color = hex_color(FRAME_CATALOG.get(theme, DEFAULT_FRAME)["primary"], 255)
    dilated = full_mask.filter(ImageFilter.MaxFilter(11))
    outline_mask = ImageChops.subtract(dilated, full_mask)
    outline = Image.new("RGBA", CANVAS, border_color)
    canvas.alpha_composite(Image.composite(outline, Image.new("RGBA", CANVAS), outline_mask))
    video_layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    video_layer.paste(raw.convert("RGBA").resize((w, h), Image.Resampling.LANCZOS), (box[0], box[1]))
    canvas.alpha_composite(Image.composite(video_layer, Image.new("RGBA", CANVAS), full_mask))
    draw = ImageDraw.Draw(canvas)
    if layout["id"] == "polaroid":
        draw.rectangle((box[0]-7, box[1]-7, box[2]+7, box[3]+14), outline=(255,255,255,255), width=9)
    elif layout["id"] == "film":
        for x in range(box[0]+10, box[2]-5, 20):
            draw.rounded_rectangle((x, box[1]-9, x+10, box[1]-2), radius=2, fill=(255,255,255,240))
            draw.rounded_rectangle((x, box[3]+2, x+10, box[3]+9), radius=2, fill=(255,255,255,240))
    draw_effect(draw, theme, index, total)

    label_font = fit_text(text, 286)
    bbox = draw.textbbox((0, 0), text, font=label_font, stroke_width=2)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (CANVAS[0] - tw) / 2
    y = 230 + (36 - th) / 2 - bbox[1]
    draw.rounded_rectangle((8, 226, 312, 269), radius=20, fill=(255, 255, 255, 245), outline=border_color, width=4)
    draw.text((x, y), text, font=label_font, fill=(36, 43, 58, 255), stroke_width=2, stroke_fill=(255, 255, 255, 255))
    return canvas


def save_apng(frames: list[Image.Image], path: Path, duration_s: int) -> None:
    frame_ms = round(duration_s * 1000 / len(frames))
    frames[0].save(
        path, save_all=True, append_images=frames[1:], duration=frame_ms,
        loop=1, disposal=1, blend=0, optimize=True, compress_level=9,
    )


def render_sticker(source: Path, slot: dict, path: Path, frame_dir: Path) -> dict:
    duration = int(slot.get("duration", 2))
    text = str(slot.get("text") or "").strip()
    if not text:
        raise RenderError("空の文字があります。8個すべてに文字を入力してください。")
    theme = str(slot.get("theme") or "sparkle")
    attempts = [20, 16, 12, 10, 8, 6, 5]
    last_size = 0
    for count in attempts:
        attempt_dir = frame_dir / str(count)
        raw_paths = extract_frames(source, slot, count, attempt_dir)
        frames = [compose(Image.open(p), text, theme, i, len(raw_paths), str(slot.get("layout") or "")) for i, p in enumerate(raw_paths)]
        save_apng(frames, path, duration)
        last_size = path.stat().st_size
        if last_size <= MAX_BYTES:
            return {"frames": len(frames), "bytes": last_size, "duration": duration, "theme": theme}
        shutil.rmtree(attempt_dir, ignore_errors=True)
    raise RenderError(f"{path.name}を1MB以下にできませんでした（{last_size / 1_000_000:.2f}MB）。動画を短くするかズームを上げてください。")


def apng_info(path: Path) -> dict:
    with Image.open(path) as image:
        n_frames = getattr(image, "n_frames", 1)
        size = image.size
        duration_ms = sum(int(image.seek(i) or image.info.get("duration", 0)) for i in range(n_frames))
    return {"width": size[0], "height": size[1], "frames": n_frames, "duration_ms": duration_ms, "bytes": path.stat().st_size}


def create_auxiliary(first_path: Path, output: Path) -> None:
    with Image.open(first_path) as source:
        frames = []
        durations = []
        for i in range(source.n_frames):
            source.seek(i)
            frame = source.convert("RGBA")
            frame.thumbnail((240, 202), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
            canvas.alpha_composite(frame, ((240 - frame.width) // 2, (240 - frame.height) // 2))
            frames.append(canvas)
            durations.append(source.info.get("duration", 100))
        frames[0].save(output / "main.png", save_all=True, append_images=frames[1:], duration=durations, loop=1, disposal=1, blend=0, optimize=True, compress_level=9)
        source.seek(0)
        tab = source.convert("RGBA")
        tab.thumbnail((96, 74), Image.Resampling.LANCZOS)
        tab_canvas = Image.new("RGBA", (96, 74), (0, 0, 0, 0))
        tab_canvas.alpha_composite(tab, ((96 - tab.width) // 2, (74 - tab.height) // 2))
        tab_canvas.save(output / "tab.png", optimize=True)


def validate_auxiliary(output: Path) -> None:
    main = output / "main.png"
    tab = output / "tab.png"
    with Image.open(main) as image:
        if image.size != (240, 240) or getattr(image, "n_frames", 1) < 5 or main.stat().st_size > MAX_BYTES:
            raise RenderError("main.pngがLINE仕様の自動検査に通りませんでした。")
    with Image.open(tab) as image:
        if image.size != (96, 74) or tab.stat().st_size > MAX_BYTES:
            raise RenderError("tab.pngがLINE仕様の自動検査に通りませんでした。")


def render_package(source: Path, config: dict, job_dir: Path) -> tuple[Path, list[dict]]:
    info = probe_video(source)
    if not isinstance(config, dict):
        raise RenderError("設定データの形式が不正です。")
    slots = config.get("slots")
    if not isinstance(slots, list) or len(slots) != 8:
        raise RenderError("切り出し設定は8個必要です。")
    for i, slot in enumerate(slots):
        if not isinstance(slot, dict):
            raise RenderError(f"{i + 1}番の設定形式が不正です。")
        try:
            duration = int(slot.get("duration", 2))
            start = float(slot.get("start", 0))
            focus_x = float(slot.get("focusX", 0.5))
            focus_y = float(slot.get("focusY", 0.5))
            zoom = float(slot.get("zoom", 1.0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RenderError(f"{i + 1}番の数値設定が不正です。") from exc
        if not all(math.isfinite(value) for value in (start, focus_x, focus_y, zoom)):
            raise RenderError(f"{i + 1}番の数値設定が不正です。")
        if duration not in (1, 2, 3, 4):
            raise RenderError(f"{i + 1}番の長さは1〜4秒の整数にしてください。")
        if start < 0 or start + duration > info["duration"] + 0.05:
            raise RenderError(f"{i + 1}番の指定区間が動画の長さを超えています。")
        if not (0 <= focus_x <= 1 and 0 <= focus_y <= 1 and 1 <= zoom <= 2.2):
            raise RenderError(f"{i + 1}番の位置またはズーム設定が範囲外です。")
        text = str(slot.get("text") or "").strip()
        if not text or len(text) > 18:
            raise RenderError(f"{i + 1}番の文字は1〜18文字にしてください。")
        if str(slot.get("theme") or "") not in FRAME_CATALOG:
            raise RenderError(f"{i + 1}番の動くフレームが不正です。")
        if str(slot.get("layout") or "") not in LAYOUT_BY_ID:
            raise RenderError(f"{i + 1}番の輪郭が不正です。")

    output = job_dir / "LINE_APNG_8"
    if output.exists():
        shutil.rmtree(output, ignore_errors=True)
    output.mkdir(mode=0o700)
    report = []
    for index, slot in enumerate(slots, 1):
        target = output / f"{index:02d}.png"
        result = render_sticker(source, slot, target, job_dir / f"frames-{index:02d}")
        validated = apng_info(target)
        if not (5 <= validated["frames"] <= 20 and validated["bytes"] <= MAX_BYTES):
            raise RenderError(f"{target.name}がLINE仕様の自動検査に通りませんでした。")
        report.append({"file": target.name, **result})

    create_auxiliary(output / "01.png", output)
    validate_auxiliary(output)
    (output / "検査結果.json").write_text(json.dumps({"source_duration": info["duration"], "stickers": report}, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "README.txt").write_text(
        "LINE Creators Market用の生成物です。\n"
        "01.png〜08.png: アニメーションスタンプ\nmain.png: メイン画像（APNG）\ntab.png: トークルームタブ画像\n"
        "アップロード前に必ず全画像を目視確認してください。子どもの顔・氏名・住所・制服・位置情報などが映っていたら申請を停止してください。\n",
        encoding="utf-8",
    )
    archive = job_dir / "LINE_APNG_8.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(output.iterdir()):
            zf.write(item, arcname=item.name)
    return archive, report
