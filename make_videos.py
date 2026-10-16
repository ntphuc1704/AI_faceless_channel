import json
import os
import random
import shutil
import subprocess
import sys
import time
import wave
import struct
import math
from array import array
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# ============================================================
# CONFIG
# ============================================================

SCENES_FILE = Path("scenes.json")
VISUALS_FILE = Path("visuals.json")
VISUALS_DIR = Path("visuals")
TEMP_DIR = Path("video_temp")

OUTPUT_VIDEO = Path("final_video.mp4")
VOICE_FILE = Path("voice.wav")

WIDTH = 1920
HEIGHT = 1080
FPS = 30

ENCODE_THREADS = min(4, max(2, os.cpu_count() or 4))

PRESET = "ultrafast"
CRF = "23"

MAX_CLIPS_PER_SCENE = 2

SUBTITLE_MODEL = "small"
SUBTITLE_WORDS_PER_GROUP = 5
SUBTITLE_FONT = "Arial"
SUBTITLE_FONT_SIZE = 72
SUBTITLE_MARGIN_VERTICAL = 70
SUBTITLE_OUTLINE = 3
SUBTITLE_SHADOW = 2

CARD_TYPES = {
    "section_card",
    "point",
    "highlight",
    "stat",
    "warning",
    "summary",
    "outro",
}


# ============================================================
# COLORS
# ============================================================

BG = (8, 10, 15)
WHITE = (245, 245, 245)
GRAY = (155, 160, 170)
DARK_GRAY = (45, 48, 55)
ACCENT = (255, 190, 60)
RED = (235, 70, 70)


# ============================================================
# HELPERS
# ============================================================

def run(cmd, description="FFmpeg"):
    print()
    print(">", description)
    print(" ".join(str(x) for x in cmd))

    result = subprocess.run(cmd)

    if result.returncode != 0:
        raise RuntimeError(
            f"{description} failed with exit code {result.returncode}"
        )


def ffprobe_duration(path):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return 0.0

    try:
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def find_font(bold=False):
    if os.name == "nt":
        if bold:
            candidates = [
                r"C:\Windows\Fonts\arialbd.ttf",
                r"C:\Windows\Fonts\segoeuib.ttf",
                r"C:\Windows\Fonts\calibrib.ttf",
            ]
        else:
            candidates = [
                r"C:\Windows\Fonts\arial.ttf",
                r"C:\Windows\Fonts\segoeui.ttf",
                r"C:\Windows\Fonts\calibri.ttf",
            ]

        for path in candidates:
            if Path(path).exists():
                return path

    return None


def get_font(size, bold=False):
    font_path = find_font(bold)

    if font_path:
        return ImageFont.truetype(font_path, size)

    return ImageFont.load_default()


def text_bbox(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw, text, font, max_width):
    words = str(text).split()

    if not words:
        return []

    lines = []
    current = words[0]

    for word in words[1:]:
        test = current + " " + word
        width, _ = text_bbox(draw, test, font)

        if width <= max_width:
            current = test
        else:
            lines.append(current)
            current = word

    lines.append(current)

    return lines


def draw_centered_text(
    draw,
    text,
    y,
    font,
    fill,
    max_width=1600,
    spacing=15,
):
    lines = wrap_text(
        draw,
        text,
        font,
        max_width,
    )

    if not lines:
        return

    total_height = 0
    heights = []

    for line in lines:
        _, h = text_bbox(
            draw,
            line,
            font,
        )

        heights.append(h)
        total_height += h

    total_height += spacing * max(
        0,
        len(lines) - 1,
    )

    current_y = y - total_height / 2

    for line, h in zip(lines, heights):
        w, _ = text_bbox(
            draw,
            line,
            font,
        )

        x = (WIDTH - w) / 2

        draw.text(
            (x, current_y),
            line,
            font=font,
            fill=fill,
        )

        current_y += h + spacing


# ============================================================
# CARD CREATION
# ============================================================

def create_card(scene):
    scene_id = int(scene["id"])
    scene_type = scene.get("type", "")
    title = str(
        scene.get("title", "") or ""
    )
    subtitle = str(
        scene.get("subtitle", "") or ""
    )

    path = (
        TEMP_DIR
        / f"card_{scene_id:02d}.png"
    )

    card_background = (255, 255, 255) if scene_type in {"section_card", "point"} else BG
    img = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        card_background,
    )

    draw = ImageDraw.Draw(img)

    # --------------------------------------------------------
    # SECTION CARD: CLEAN WHITE NUMBERED TITLE SCREEN
    # --------------------------------------------------------

    if scene_type == "section_card":
        section_number = scene.get("section", scene.get("point_number", scene_id))
        try:
            section_number = int(section_number)
        except (TypeError, ValueError):
            section_number = scene_id

        display_text = str(
            scene.get("display_text")
            or f"{section_number:02d} — {title.upper()}"
        )
        card_font = get_font(92, True)
        draw_centered_text(
            draw,
            display_text,
            490,
            card_font,
            (15, 15, 15),
            1660,
            16,
        )

        # Minimal editorial accent; keep the screen otherwise white.
        draw.rounded_rectangle(
            (760, 625, 1160, 634),
            radius=4,
            fill=(15, 15, 15),
        )

    # --------------------------------------------------------
    # HOOK / OUTRO
    # --------------------------------------------------------

    elif scene_type in {"hook", "outro"}:
        title_font = get_font(
            110,
            True,
        )

        subtitle_font = get_font(
            48,
            False,
        )

        draw_centered_text(
            draw,
            title,
            440,
            title_font,
            WHITE,
            1650,
            18,
        )

        if subtitle:
            draw_centered_text(
                draw,
                subtitle,
                650,
                subtitle_font,
                GRAY,
                1400,
                12,
            )

        draw.rounded_rectangle(
            (
                720,
                760,
                1200,
                770,
            ),
            radius=5,
            fill=ACCENT,
        )

    # --------------------------------------------------------
    # POINT
    # --------------------------------------------------------

    elif scene_type == "point":
        number = scene.get(
            "point_number",
            scene.get("section")
        )

        number_font = get_font(
            70,
            True,
        )

        title_font = get_font(
            100,
            True,
        )

        subtitle_font = get_font(
            40,
            False,
        )

        # Point cards continue the clean white title-card look instead of
        # cutting to the default dark background immediately after the roll.
        if number is not None:
            try:
                number_label = f"#{int(number):02d}"
            except (TypeError, ValueError):
                number_label = f"#{number}"
            draw.text(
                (150, 150),
                number_label,
                font=number_font,
                fill=(15, 15, 15),
            )

        draw_centered_text(
            draw,
            title,
            480,
            title_font,
            (15, 15, 15),
            1650,
            15,
        )

        if subtitle:
            draw_centered_text(
                draw,
                subtitle,
                650,
                subtitle_font,
                (95, 95, 95),
                1500,
                10,
            )

        draw.rounded_rectangle(
            (
                150,
                820,
                1770,
                825,
            ),
            radius=2,
            fill=(15, 15, 15),
        )

    # --------------------------------------------------------
    # STAT
    # --------------------------------------------------------

    elif scene_type == "stat":
        stat_font = get_font(
            180,
            True,
        )

        subtitle_font = get_font(
            48,
            False,
        )

        draw_centered_text(
            draw,
            title,
            440,
            stat_font,
            ACCENT,
            1650,
            10,
        )

        if subtitle:
            draw_centered_text(
                draw,
                subtitle,
                690,
                subtitle_font,
                WHITE,
                1400,
                12,
            )

    # --------------------------------------------------------
    # WARNING
    # --------------------------------------------------------

    elif scene_type == "warning":
        title_font = get_font(
            90,
            True,
        )

        subtitle_font = get_font(
            46,
            False,
        )

        draw.rectangle(
            (
                0,
                0,
                WIDTH,
                18,
            ),
            fill=RED,
        )

        draw_centered_text(
            draw,
            title,
            450,
            title_font,
            WHITE,
            1600,
            15,
        )

        if subtitle:
            draw_centered_text(
                draw,
                subtitle,
                650,
                subtitle_font,
                GRAY,
                1450,
                12,
            )

        draw.rectangle(
            (
                0,
                HEIGHT - 18,
                WIDTH,
                HEIGHT,
            ),
            fill=RED,
        )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    elif scene_type == "summary":
        title_font = get_font(
            90,
            True,
        )

        subtitle_font = get_font(
            48,
            False,
        )

        draw_centered_text(
            draw,
            title,
            420,
            title_font,
            WHITE,
            1600,
            15,
        )

        if subtitle:
            draw_centered_text(
                draw,
                subtitle,
                650,
                subtitle_font,
                GRAY,
                1450,
                12,
            )

        draw.rounded_rectangle(
            (
                650,
                790,
                1270,
                798,
            ),
            radius=4,
            fill=ACCENT,
        )

    # --------------------------------------------------------
    # FALLBACK CARD
    # --------------------------------------------------------

    else:
        title_font = get_font(
            80,
            True,
        )

        subtitle_font = get_font(
            42,
            False,
        )

        draw_centered_text(
            draw,
            title,
            430,
            title_font,
            WHITE,
            1600,
            15,
        )

        if subtitle:
            draw_centered_text(
                draw,
                subtitle,
                650,
                subtitle_font,
                GRAY,
                1450,
                12,
            )

    img.save(
        path,
        "PNG",
        optimize=True,
    )

    return path


# ============================================================
# FALLBACK VISUAL CARD
# ============================================================

def create_visual_fallback(scene):
    scene_id = int(scene["id"])

    path = (
        TEMP_DIR
        / f"fallback_{scene_id:02d}.png"
    )

    img = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        (5, 7, 11),
    )

    draw = ImageDraw.Draw(img)

    title = str(
        scene.get("title", "") or ""
    ).strip()

    query = str(
        scene.get("visual_query", "") or ""
    ).strip()

    # If there is no title, use a short piece
    # of the visual query as the large text.
    if not title:
        words = query.split()

        if words:
            title = " ".join(
                words[:10]
            )

            if len(words) > 10:
                title += "..."

        else:
            title = "KEEP GOING"

    title_font = get_font(
        82,
        True,
    )

    subtitle_font = get_font(
        36,
        False,
    )

    draw_centered_text(
        draw,
        title,
        450,
        title_font,
        WHITE,
        1600,
        16,
    )

    if query and query != title:
        words = query.split()

        short_query = " ".join(
            words[:24]
        )

        if len(words) > 24:
            short_query += "..."

        draw_centered_text(
            draw,
            short_query,
            670,
            subtitle_font,
            GRAY,
            1450,
            10,
        )

    # Cinematic accent line.
    draw.rounded_rectangle(
        (
            760,
            810,
            1160,
            818,
        ),
        radius=4,
        fill=ACCENT,
    )

    img.save(
        path,
        "PNG",
        optimize=True,
    )

    return path


# ============================================================
# VISUAL FILE DISCOVERY
# ============================================================

def normalize_visuals(data):
    result = {}

    if isinstance(data, dict):
        scenes = data.get("scenes")

        if isinstance(scenes, list):
            for item in scenes:
                if not isinstance(item, dict):
                    continue

                sid = item.get(
                    "scene_id",
                    item.get("id"),
                )

                if sid is None:
                    continue

                files = (
                    item.get("files")
                    or item.get("videos")
                    or item.get("clips")
                    or []
                )

                if isinstance(files, str):
                    files = [files]

                result[int(sid)] = [
                    str(x)
                    for x in files
                    if x
                ]

        elif isinstance(scenes, dict):
            for sid, item in scenes.items():
                if isinstance(item, dict):
                    files = (
                        item.get("files")
                        or item.get("videos")
                        or item.get("clips")
                        or []
                    )
                else:
                    files = item

                if isinstance(files, str):
                    files = [files]

                result[int(sid)] = [
                    str(x)
                    for x in files
                    if x
                ]

        else:
            for sid, item in data.items():
                try:
                    sid_int = int(sid)
                except Exception:
                    continue

                if isinstance(item, dict):
                    files = (
                        item.get("files")
                        or item.get("videos")
                        or item.get("clips")
                        or []
                    )
                else:
                    files = item

                if isinstance(files, str):
                    files = [files]

                result[sid_int] = [
                    str(x)
                    for x in files
                    if x
                ]

    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue

            sid = item.get(
                "scene_id",
                item.get("id"),
            )

            if sid is None:
                continue

            files = (
                item.get("files")
                or item.get("videos")
                or item.get("clips")
                or []
            )

            if isinstance(files, str):
                files = [files]

            result[int(sid)] = [
                str(x)
                for x in files
                if x
            ]

    return result


def load_visuals():
    if not VISUALS_FILE.exists():
        return {}

    try:
        with open(
            VISUALS_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            return normalize_visuals(
                json.load(f)
            )
    except Exception as e:
        print(
            f"WARNING: Could not read "
            f"{VISUALS_FILE}: {e}"
        )

        return {}


def discover_scene_clips(
    scene_id,
    visuals,
):
    files = visuals.get(
        scene_id,
        [],
    )

    found = []

    for file in files:
        path = Path(file)

        if not path.is_absolute():
            path = (
                Path.cwd()
                / path
            )

        if (
            path.exists()
            and path.is_file()
        ):
            found.append(path)

    # Fallback:
    # visuals/scene_XX/
    folder = (
        VISUALS_DIR
        / f"scene_{scene_id:02d}"
    )

    if folder.exists():
        for path in sorted(
            folder.glob("*")
        ):
            if path.suffix.lower() in {
                ".mp4",
                ".mov",
                ".mkv",
                ".webm",
                ".m4v",
            }:
                if path not in found:
                    found.append(path)

    return found


# ============================================================
# RENDER VISUAL SCENE
# ============================================================

def render_visual_scene(
    scene,
    output,
    visuals,
):
    scene_id = int(
        scene["id"]
    )

    duration = float(
        scene["duration"]
    )

    clips = discover_scene_clips(
        scene_id,
        visuals,
    )

    # --------------------------------------------------------
    # NORMAL VISUAL
    # --------------------------------------------------------

    if clips:
        clip = random.choice(
            clips[:MAX_CLIPS_PER_SCENE]
        )

        print(
            f"  Scene {scene_id}: visual "
            f"{clip.name} "
            f"({duration:.2f}s)"
        )

        vf = (
            f"scale={WIDTH}:{HEIGHT}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},"
            f"setsar=1,"
            f"fps={FPS}"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",

            "-stream_loop",
            "-1",
            "-i",
            str(clip),

            "-frames:v",
            str(max(1, int(round(duration * FPS)))),

            "-vf",
            vf,

            "-an",

            "-c:v",
            "libx264",
            "-preset",
            PRESET,
            "-crf",
            CRF,

            "-threads",
            str(ENCODE_THREADS),

            "-pix_fmt",
            "yuv420p",

            "-movflags",
            "+faststart",

            str(output),
        ]

        run(
            cmd,
            f"Rendering visual scene {scene_id}",
        )

        return

    # --------------------------------------------------------
    # MISSING VISUAL FALLBACK
    # --------------------------------------------------------

    print()
    print(
        f"  WARNING: No visual clips found "
        f"for scene {scene_id}"
    )

    print(
        f"  Creating cinematic fallback card "
        f"instead."
    )

    card = create_visual_fallback(
        scene
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",

        "-loop",
        "1",
        "-i",
        str(card),

        "-frames:v",
        str(max(1, int(round(duration * FPS)))),

        "-r",
        str(FPS),

        "-an",

        "-c:v",
        "libx264",
        "-preset",
        PRESET,
        "-crf",
        CRF,

        "-threads",
        str(ENCODE_THREADS),

        "-pix_fmt",
        "yuv420p",

        str(output),
    ]

    run(
        cmd,
        f"Rendering fallback scene {scene_id}",
    )


def render_typewriter_title(scene, output):
    """
    Render a clean white section card with a typewriter reveal and a smooth
    upward roll-out. The background is white on EVERY frame, including the
    final frames, so this function cannot create a black flash at the end.
    """
    scene_id = int(scene["id"])
    duration = max(1.0 / FPS, float(scene["duration"]))
    text = str(scene.get("display_text") or scene.get("title") or "").strip()
    if not text:
        section_number = scene.get("section", 1)
        try:
            section_number = int(section_number)
        except (TypeError, ValueError):
            section_number = 1
        text = f"{section_number:02d} — OPPORTUNITY"

    frames_dir = TEMP_DIR / f"title_frames_{scene_id:02d}"
    frames_dir.mkdir(parents=True, exist_ok=True)

    frame_count = max(1, int(round(duration * FPS)))
    actual_duration = frame_count / FPS

    # Keep enough time for the title to be read, even on short cards.
    enter_duration = min(0.42, actual_duration * 0.18)
    exit_duration = min(0.38, actual_duration * 0.18)
    type_duration = min(1.25, max(0.65, actual_duration * 0.50))
    exit_start = max(enter_duration + 0.15, actual_duration - exit_duration)
    exit_start = min(exit_start, max(enter_duration, actual_duration - 1.0 / FPS))

    font_size = 104
    probe_img = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    probe = ImageDraw.Draw(probe_img)
    font = get_font(font_size, True)

    # Shrink long titles to fit on one line where possible.
    while font_size > 54 and text_bbox(probe, text, font)[0] > WIDTH - 260:
        font_size -= 4
        font = get_font(font_size, True)

    # Wrap exceptionally long titles rather than clipping them.
    lines = wrap_text(probe, text, font, WIDTH - 260)
    if not lines:
        lines = [text]

    line_heights = [text_bbox(probe, line, font)[1] for line in lines]
    text_height = sum(line_heights) + 12 * max(0, len(lines) - 1)
    max_line_width = max(text_bbox(probe, line, font)[0] for line in lines)
    base_x = (WIDTH - max_line_width) // 2
    base_y = (HEIGHT - text_height) // 2 - 24

    def ease_out(value):
        value = max(0.0, min(1.0, value))
        return 1.0 - (1.0 - value) ** 3

    def draw_title(draw, visible_text, x, y, color):
        # Keep the layout fixed to the final wrapped title. Revealing a prefix
        # and wrapping that prefix again makes the words jump/rearrange on the
        # white card as each new character appears.
        remaining = len(visible_text)
        current_y = y
        for line, line_h in zip(lines, line_heights):
            shown = line[:max(0, min(len(line), remaining))]
            remaining -= len(line)
            line_w, _ = text_bbox(draw, line, font)
            shown_w, _ = text_bbox(draw, shown, font)
            # Anchor the typed prefix to the same left edge as its final line;
            # only the glyphs appear, rather than the whole line shifting.
            line_x = (WIDTH - line_w) // 2
            if shown:
                draw.text((line_x, current_y), shown, font=font, fill=color)
            current_y += line_h + 12

    for frame_index in range(frame_count):
        t = frame_index / FPS
        img = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Keep the last frames completely blank white. This also gives the
        # concatenated video a clean white ending for this card.
        if t < exit_start:
            type_progress = min(1.0, max(0.0, t / max(0.01, type_duration)))
            visible_chars = min(
                len(text),
                max(0, int(math.floor(type_progress * len(text) + 0.001))),
            )
            visible_text = text[:visible_chars]

            enter_progress = ease_out(t / max(0.01, enter_duration))
            y_offset = int((1.0 - enter_progress) * 115)
            ink = 12

            if visible_text:
                draw_title(draw, visible_text, base_x, base_y + y_offset, (ink, ink, ink))

            # Underline draws in after the title begins to appear.
            line_progress = min(1.0, max(0.0, (type_progress - 0.28) / 0.72))
            line_width = int(320 * line_progress)
            if line_width > 0:
                line_y = 625 + y_offset
                draw.rounded_rectangle(
                    (
                        WIDTH // 2 - line_width // 2,
                        line_y,
                        WIDTH // 2 + line_width // 2,
                        line_y + 8,
                    ),
                    radius=4,
                    fill=(12, 12, 12),
                )
        else:
            # Roll the fully readable title upward, then leave a clean white
            # tail. The background itself never fades to black or gray.
            exit_progress = ease_out(
                (t - exit_start) / max(0.01, actual_duration - exit_start)
            )
            roll_y = base_y - int(exit_progress * (text_height + 260))
            fade = max(
                0.0,
                1.0 - (t - exit_start) / max(0.01, actual_duration - exit_start),
            )
            ink = int(12 + 243 * (1.0 - fade))
            if fade > 0.04:
                draw_title(draw, text, base_x, roll_y, (ink, ink, ink))

            line_fade = fade
            line_width = int(320 * line_fade)
            if line_width > 0:
                line_y = 625 - int(exit_progress * (text_height + 260))
                draw.rounded_rectangle(
                    (
                        WIDTH // 2 - line_width // 2,
                        line_y,
                        WIDTH // 2 + line_width // 2,
                        line_y + 8,
                    ),
                    radius=4,
                    fill=(ink, ink, ink),
                )

        # Explicitly guarantee a pure-white ending, even if timing is rounded.
        if frame_index >= frame_count - max(2, int(round(0.08 * FPS))):
            img = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))

        img.save(frames_dir / f"frame_{frame_index:05d}.png", "PNG", optimize=True)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        "-framerate", str(FPS),
        "-start_number", "0",
        "-i", str(frames_dir / "frame_%05d.png"),
        "-frames:v", str(frame_count),
        "-r", str(FPS),
        "-an",
        "-c:v", "libx264",
        "-preset", PRESET,
        "-crf", CRF,
        "-threads", str(ENCODE_THREADS),
        "-pix_fmt", "yuv420p",
        "-video_track_timescale", "90000",
        str(output),
    ]
    run(cmd, f"Rendering rolling white title scene {scene_id}")


def create_typing_soundtrack(scenes, output_wav, total_duration):
    """Create subtle synthetic keyboard ticks aligned to title character reveals."""
    sample_rate = 44100
    total_samples = max(1, int(math.ceil(total_duration * sample_rate)))
    # Signed 16-bit storage avoids the huge memory overhead of a Python-float
    # list for a full-length video soundtrack.
    audio = array("h", [0]) * total_samples
    rng = random.Random(20261014)
    click_len = int(sample_rate * 0.022)

    for scene in scenes:
        if scene.get("type") != "section_card" or not scene.get("typing_sound", True):
            continue
        start = float(scene.get("start", 0.0))
        duration = float(scene.get("duration", 0.0))
        title = str(scene.get("display_text") or scene.get("title") or "")
        chars = [i for i, ch in enumerate(title) if not ch.isspace()]
        if not chars:
            continue
        typing_window = min(1.35, max(0.65, duration * 0.58))
        for order, char_index in enumerate(chars):
            event_time = start + 0.08 + typing_window * (order / max(1, len(chars) - 1))
            event_start = int(event_time * sample_rate)
            if event_start >= total_samples:
                continue
            strength = 0.20 if title[char_index].isalnum() else 0.12
            for j in range(click_len):
                pos = event_start + j
                if pos >= total_samples:
                    break
                t = j / sample_rate
                envelope = math.exp(-t * 190.0)
                noise = rng.uniform(-1.0, 1.0)
                tone = math.sin(2.0 * math.pi * (1650.0 - 900.0 * t) * t)
                sample = strength * envelope * (0.72 * noise + 0.28 * tone)
                mixed = audio[pos] + int(sample * 32767)
                audio[pos] = max(-32768, min(32767, mixed))

    with wave.open(str(output_wav), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio.tobytes())


# ============================================================
# RENDER CARD SCENE
# ============================================================

def render_card_scene(
    scene,
    output,
):
    scene_id = int(
        scene["id"]
    )

    duration = float(
        scene["duration"]
    )

    # Every section card gets the animated white rolling-title treatment,
    # regardless of whether scenes.json labels it roll_in, roll_out,
    # rolling_text, or typewriter_roll.
    if scene.get("type") == "section_card":
        render_typewriter_title(scene, output)
        return

    card = create_card(
        scene
    )

    print(
        f"  Scene {scene_id}: "
        f"{scene.get('type')} "
        f"({duration:.2f}s)"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",

        "-loop",
        "1",
        "-i",
        str(card),

        "-t",
        f"{duration:.3f}",

        "-r",
        str(FPS),

        "-an",

        "-c:v",
        "libx264",
        "-preset",
        PRESET,
        "-crf",
        CRF,

        "-threads",
        str(ENCODE_THREADS),

        "-pix_fmt",
        "yuv420p",

        str(output),
    ]

    run(
        cmd,
        f"Rendering card scene {scene_id}",
    )


# ============================================================
# CONCAT
# ============================================================

def concat_scenes(
    scene_files,
    output,
):
    """Normalize every scene independently, then concatenate compatible clips.

    The concat demuxer can mis-handle timestamps when inputs have different
    stream layouts or time bases. Re-encode each scene to a canonical video-only
    format first, resetting PTS to frame order, then concatenate those uniform
    files by stream copy.
    """
    normalized_dir = TEMP_DIR / "normalized_scenes"
    normalized_dir.mkdir(parents=True, exist_ok=True)

    normalized_files = []
    total = len(scene_files)

    for index, source in enumerate(scene_files, start=1):
        normalized = normalized_dir / f"scene_{index:04d}.mp4"
        print(f"  Normalizing scene {index}/{total}: {source.name}")

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
            "-fflags", "+genpts",
            "-i", str(source),
            "-map", "0:v:0",
            "-an",
            "-vf", f"setpts=PTS-STARTPTS,fps={FPS},setpts=N/({FPS}*TB),format=yuv420p",
            "-fps_mode", "cfr",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-threads", str(ENCODE_THREADS),
            "-r", str(FPS),
            "-video_track_timescale", "90000",
            "-movflags", "+faststart",
            str(normalized),
        ]
        run(cmd, f"Normalizing scene {index}/{total}")

        if not normalized.exists() or normalized.stat().st_size == 0:
            raise RuntimeError(f"Normalized scene was not created: {normalized}")

        normalized_files.append(normalized)

    concat_file = TEMP_DIR / "concat_normalized.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for path in normalized_files:
            p = path.resolve().as_posix().replace("'", "'\\''")
            f.write(f"file '{p}'\n")

    print("\nConcatenating normalized scenes...")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-map", "0:v:0", "-an",
        "-c:v", "copy",
        "-video_track_timescale", "90000",
        "-movflags", "+faststart",
        str(output),
    ]
    run(cmd, "Concatenating normalized scenes")


# ============================================================
# ADD VOICE
# ============================================================

def add_voice(video, output, scenes=None):
    if not VOICE_FILE.exists():
        raise RuntimeError(f"{VOICE_FILE} not found.")

    print()
    print("Adding narration and title typing sounds...")

    scenes = scenes or []
    title_scenes = [
        scene for scene in scenes
        if scene.get("type") == "section_card" and scene.get("typing_sound", True)
    ]

    base_cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        "-i", str(video),
        "-i", str(VOICE_FILE),
    ]

    if title_scenes:
        total_duration = max(float(scene.get("end", 0.0)) for scene in scenes)
        typing_wav = TEMP_DIR / "typing_sfx.wav"
        create_typing_soundtrack(scenes, typing_wav, total_duration)
        cmd = base_cmd + [
            "-i", str(typing_wav),
            "-filter_complex",
            "[1:a]volume=1.0[voice];[2:a]volume=0.22[typing];"
            "[voice][typing]amix=inputs=2:duration=first:dropout_transition=0[aout]",
            "-map", "0:v:0",
            "-map", "[aout]",
        ]
    else:
        cmd = base_cmd + [
            "-map", "0:v:0",
            "-map", "1:a:0",
        ]

    cmd += [
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output),
    ]

    run(cmd, "Adding narration and typing sound effects")


# ============================================================
# SUBTITLES
# ============================================================

def subtitle_ass_time(seconds):
    seconds = max(0.0, float(seconds))
    total_cs = int(round(seconds * 100))
    h, remainder = divmod(total_cs, 360000)
    m, remainder = divmod(remainder, 6000)
    sec, cs = divmod(remainder, 100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"


def subtitle_escape_ass(text):
    return str(text).replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def transcribe_subtitle_words():
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Subtitles require faster-whisper. Install it with: "
            "python -m pip install faster-whisper"
        ) from exc

    print("\nGenerating word-level subtitle timestamps with Whisper...")
    model = WhisperModel(SUBTITLE_MODEL, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(VOICE_FILE),
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,
        beam_size=5,
    )
    words = []
    for segment in segments:
        for word in (segment.words or []):
            text = (word.word or "").strip()
            if not text or word.start is None or word.end is None:
                continue
            start, end = float(word.start), float(word.end)
            if end > start >= 0:
                words.append({"text": text, "start": start, "end": end})
    if not words:
        raise RuntimeError("Whisper did not detect any words for subtitles.")
    print(f"Detected {len(words)} words for subtitles.")
    return words


def subtract_intervals(start, end, excluded_intervals):
    """Return portions of [start, end] that do not overlap excluded title cards."""
    pieces = [(start, end)]
    for ex_start, ex_end in excluded_intervals:
        next_pieces = []
        for left, right in pieces:
            if ex_end <= left or ex_start >= right:
                next_pieces.append((left, right))
                continue
            if ex_start > left:
                next_pieces.append((left, min(ex_start, right)))
            if ex_end < right:
                next_pieces.append((max(ex_end, left), right))
        pieces = next_pieces
        if not pieces:
            break
    return [(a, b) for a, b in pieces if b - a >= 0.035]


def build_subtitle_ass(words, scenes):
    subtitle_dir = TEMP_DIR / "subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    ass_path = subtitle_dir / "rolling_subtitles.ass"

    # Title-card intervals are deliberately excluded so no narration caption
    # appears over the white rolling/typewriter title reveals.
    title_intervals = sorted(
        (float(scene.get("start", 0.0)), float(scene.get("end", 0.0)))
        for scene in scenes
        if scene.get("type") == "section_card"
        and float(scene.get("end", 0.0)) > float(scene.get("start", 0.0))
    )

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{SUBTITLE_FONT},{SUBTITLE_FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{SUBTITLE_OUTLINE},{SUBTITLE_SHADOW},2,40,40,{SUBTITLE_MARGIN_VERTICAL},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for i, word in enumerate(words):
        start = float(word["start"])
        if i + 1 < len(words):
            end = float(words[i + 1]["start"])
        else:
            end = float(word["end"])
        if end <= start:
            end = float(word["end"])
        if end <= start:
            continue

        first = max(0, i - SUBTITLE_WORDS_PER_GROUP + 1)
        visible_words = words[first:i + 1]
        caption = " ".join(subtitle_escape_ass(w["text"]) for w in visible_words)

        for piece_start, piece_end in subtract_intervals(start, end, title_intervals):
            lines.append(
                f"Dialogue: 0,{subtitle_ass_time(piece_start)},{subtitle_ass_time(piece_end)},Default,,0,0,0,,{caption}"
            )

    ass_path.write_text("\n".join(lines), encoding="utf-8-sig")
    print("Subtitles prepared; section title cards are excluded.")
    return ass_path


def ffmpeg_filter_path(path):
    value = str(path.resolve()).replace("\\", "/")
    value = value.replace(":", r"\:").replace("'", r"\'")
    return value


def burn_subtitles_into_video(video, output, scenes):
    words = transcribe_subtitle_words()
    ass_path = build_subtitle_ass(words, scenes)
    subtitle_path = ffmpeg_filter_path(ass_path)
    print("Burning rolling subtitles directly into final_video.mp4...")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        "-i", str(video),
        "-vf", f"ass='{subtitle_path}'",
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-c:v", "libx264",
        "-preset", PRESET,
        "-crf", "18",
        "-threads", str(ENCODE_THREADS),
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output),
    ]
    run(cmd, "Burning subtitles into final video")
    if not output.exists() or output.stat().st_size < 100_000:
        raise RuntimeError("Subtitled final video was not created correctly.")
    return output


def align_scene_boundaries_to_frames(scenes):
    """Snap every shared scene boundary to a 30 FPS frame to prevent cumulative drift."""
    if not scenes:
        return
    ordered = sorted(scenes, key=lambda item: (float(item.get("start", 0.0)), int(item.get("id", 0))))
    for scene in ordered:
        start = float(scene.get("start", 0.0))
        end = float(scene.get("end", start + float(scene.get("duration", 0.0))))
        start_frame = max(0, int(round(start * FPS)))
        end_frame = max(start_frame + 1, int(round(end * FPS)))
        scene["start"] = start_frame / FPS
        scene["end"] = end_frame / FPS
        scene["duration"] = (end_frame - start_frame) / FPS


# ============================================================
# MAIN
# ============================================================

def main():
    start_time = time.time()

    print("=" * 60)
    print(
        "AI FACELESS CHANNEL - "
        "CPU-FRIENDLY VIDEO RENDERER"
    )
    print("=" * 60)

    print()
    print(
        f"CPU threads: {ENCODE_THREADS}"
    )

    print(
        f"Resolution:  {WIDTH}x{HEIGHT}"
    )

    print(
        f"FPS:         {FPS}"
    )

    print(
        f"Preset:      {PRESET}"
    )

    print(
        f"CRF:         {CRF}"
    )

    # --------------------------------------------------------
    # CHECK
    # --------------------------------------------------------

    if not SCENES_FILE.exists():
        raise FileNotFoundError(
            f"Missing {SCENES_FILE}"
        )

    # --------------------------------------------------------
    # LOAD SCENES
    # --------------------------------------------------------

    with open(
        SCENES_FILE,
        "r",
        encoding="utf-8",
    ) as f:
        data = json.load(f)

    scenes = data.get(
        "scenes",
        []
    )

    if not scenes:
        raise RuntimeError(
            "No scenes found in scenes.json"
        )

    # Snap scene boundaries to exact frame boundaries before rendering. This
    # prevents per-clip rounding from accumulating into audio/video drift.
    align_scene_boundaries_to_frames(scenes)

    total_duration = float(
        data.get(
            "total_duration",
            sum(
                float(
                    x.get(
                        "duration",
                        0
                    )
                )
                for x in scenes
            ),
        )
    )

    print()
    print(
        f"Scenes: {len(scenes)}"
    )

    print(
        f"Target duration: "
        f"{total_duration:.2f}s "
        f"({total_duration / 60:.2f} min)"
    )

    # --------------------------------------------------------
    # LOAD VISUALS
    # --------------------------------------------------------

    visuals = load_visuals()

    # --------------------------------------------------------
    # CLEAN OLD TEMP
    # --------------------------------------------------------

    if TEMP_DIR.exists():
        print()
        print(
            "Cleaning previous "
            "video_temp..."
        )

        shutil.rmtree(
            TEMP_DIR
        )

    TEMP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # RENDER
    # --------------------------------------------------------

    scene_files = []

    fallback_count = 0

    try:
        for index, scene in enumerate(
            scenes,
            start=1,
        ):
            scene_id = int(
                scene["id"]
            )

            scene_type = scene.get(
                "type",
                "visual",
            )

            output = (
                TEMP_DIR
                / f"scene_{scene_id:02d}.mp4"
            )

            print()
            print(
                f"[{index}/{len(scenes)}] "
                f"Scene {scene_id} "
                f"({scene_type})"
            )

            if scene_type in CARD_TYPES:
                render_card_scene(
                    scene,
                    output,
                )

            else:
                clips_before = discover_scene_clips(
                    scene_id,
                    visuals,
                )

                if not clips_before:
                    fallback_count += 1

                render_visual_scene(
                    scene,
                    output,
                    visuals,
                )

            if not output.exists():
                raise RuntimeError(
                    f"Scene {scene_id} "
                    f"was not created."
                )

            scene_files.append(
                output
            )

        # ----------------------------------------------------
        # CONCAT
        # ----------------------------------------------------

        concat_video = (
            TEMP_DIR
            / "video_no_voice.mp4"
        )

        concat_scenes(
            scene_files,
            concat_video,
        )

        if not concat_video.exists():
            raise RuntimeError(
                "Concatenated video "
                "was not created."
            )

        # ----------------------------------------------------
        # ADD VOICE
        # ----------------------------------------------------

        voiced_video = TEMP_DIR / "video_with_voice.mp4"
        add_voice(
            concat_video,
            voiced_video,
            scenes,
        )

        if not voiced_video.exists():
            raise RuntimeError(
                "Video with narration was not created."
            )

        burn_subtitles_into_video(
            voiced_video,
            OUTPUT_VIDEO,
            scenes,
        )

        if not OUTPUT_VIDEO.exists():
            raise RuntimeError(
                "Final subtitled video was not created."
            )

        size = OUTPUT_VIDEO.stat().st_size

        if size < 100_000:
            raise RuntimeError(
                "Final video is "
                "suspiciously small."
            )

        duration = ffprobe_duration(
            OUTPUT_VIDEO
        )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        elapsed = (
            time.time()
            - start_time
        )

        print()
        print("=" * 60)
        print(
            "VIDEO CREATED SUCCESSFULLY"
        )
        print("=" * 60)

        print()
        print(
            f"File:      {OUTPUT_VIDEO}"
        )

        print(
            f"Size:      "
            f"{size / (1024 * 1024):.2f} MB"
        )

        print(
            f"Duration:  "
            f"{duration:.2f}s"
        )

        print(
            f"Time:      "
            f"{elapsed / 60:.2f} minutes"
        )

        if fallback_count:
            print()
            print(
                f"Visual fallbacks used: "
                f"{fallback_count}"
            )

            print(
                "Missing visual footage did "
                "NOT stop the render."
            )

        print()
        print(
            "Cleaning temporary "
            "render files..."
        )

        shutil.rmtree(
            TEMP_DIR,
            ignore_errors=True,
        )

        print(
            "video_temp deleted."
        )

        print()
        print(
            "Permanent/source files "
            "were NOT deleted."
        )

        print()
        print("Narration, typing sound effects, and rolling subtitles are included.")
        print("Subtitles are automatically hidden during white section-title cards.")

    except KeyboardInterrupt:
        print()
        print(
            "Rendering cancelled."
        )

        print(
            "video_temp was kept."
        )

        raise

    except Exception as e:
        print()
        print("=" * 60)
        print(
            "VIDEO CREATION FAILED"
        )
        print("=" * 60)

        print()
        print(str(e))

        print()
        print(
            "Temporary files were NOT "
            "deleted because the render "
            "failed."
        )

        raise


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        sys.exit(130)

    except Exception:
        sys.exit(1)
