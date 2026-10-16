import subprocess
import sys
from pathlib import Path

from faster_whisper import WhisperModel

VIDEO_FILE = "final_video.mp4"
AUDIO_FILE = "voice.wav"
TEMP_DIR = Path("subtitle_temp")
ASS_FILE = TEMP_DIR / "word_subtitles.ass"

MODEL_SIZE = "small"
WORDS_PER_GROUP = 5

FONT_NAME = "Arial"
FONT_SIZE = 72
MARGIN_VERTICAL = 70
OUTLINE = 3
SHADOW = 2


def run(cmd):
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        raise RuntimeError("Command failed")
    return result.stdout


def ass_time(seconds):
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int(round((s - int(s)) * 100))
    s = int(s)
    if cs >= 100:
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def escape_ass(text):
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def get_words():
    print("\n==============================")
    print("GENERATING WORD TIMESTAMPS")
    print("==============================\n")
    print(f"Model: {MODEL_SIZE}")
    print("Loading Whisper model...")
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    print("Transcribing audio...\n")
    segments, _info = model.transcribe(
        AUDIO_FILE,
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,
        beam_size=5,
    )
    words = []
    for segment in segments:
        if not segment.words:
            continue
        for word in segment.words:
            text = word.word.strip()
            if not text or word.start is None or word.end is None:
                continue
            words.append({"text": text, "start": float(word.start), "end": float(word.end)})
    if not words:
        raise RuntimeError("Whisper did not detect any words.")
    print(f"Detected {len(words)} words.")
    return words


def build_rolling_subtitles(words):
    TEMP_DIR.mkdir(exist_ok=True)
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
        f"Style: Default,{FONT_NAME},{FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{OUTLINE},{SHADOW},2,40,40,{MARGIN_VERTICAL},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for i, word in enumerate(words):
        start = word["start"]
        end = words[i + 1]["start"] if i + 1 < len(words) else word["end"]
        if end <= start:
            end = word["end"]
        first = max(0, i - WORDS_PER_GROUP + 1)
        visible_words = words[first:i + 1]
        text = " ".join(escape_ass(w["text"]) for w in visible_words)
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}")
    ASS_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Created rolling subtitles: {ASS_FILE}")


def escape_ffmpeg_path(path):
    value = str(path.resolve()).replace("\\", "/")
    value = value.replace(":", r"\:").replace("'", r"\'")
    return value


def burn_subtitles():
    print("\n==============================")
    print("BURNING SUBTITLES + RESTORING NARRATION")
    print("==============================\n")
    output = TEMP_DIR / "final_subtitled.mp4"
    subtitle_path = escape_ffmpeg_path(ASS_FILE)

    # Important: use voice.wav as the output audio source instead of copying
    # whatever audio happens to be present in the incoming video.
    cmd = [
        "ffmpeg", "-y",
        "-i", VIDEO_FILE,
        "-i", AUDIO_FILE,
        "-vf", f"ass='{subtitle_path}'",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output),
    ]
    run(cmd)
    if not output.exists() or output.stat().st_size < 100_000:
        raise RuntimeError("Subtitle video was not created correctly.")
    return output


def replace_video(output):
    backup = TEMP_DIR / "original_before_subtitles.mp4"
    Path(VIDEO_FILE).replace(backup)
    try:
        output.replace(VIDEO_FILE)
    except Exception:
        backup.replace(VIDEO_FILE)
        raise
    if backup.exists():
        backup.unlink()


def main():
    print("======================================")
    print("ROLLING WORD SUBTITLES")
    print("======================================")
    try:
        if not Path(VIDEO_FILE).exists():
            raise FileNotFoundError(f"Missing {VIDEO_FILE}")
        if not Path(AUDIO_FILE).exists():
            raise FileNotFoundError(f"Missing {AUDIO_FILE}")
        words = get_words()
        build_rolling_subtitles(words)
        output = burn_subtitles()
        replace_video(output)
        print("\n======================================")
        print("SUBTITLES COMPLETE")
        print("======================================")
        print("Narration is now explicitly mapped from voice.wav.")
        print(f"Maximum visible words: {WORDS_PER_GROUP}")
        if TEMP_DIR.exists():
            for file in TEMP_DIR.iterdir():
                if file.is_file():
                    try:
                        file.unlink()
                    except Exception:
                        pass
        print("\nTemporary subtitle files cleaned.")
    except Exception as e:
        print("\n======================================")
        print("SUBTITLE PROCESS FAILED")
        print("======================================\n")
        print(e)
        print("\nOriginal video was NOT replaced if rendering failed.")
        print(f"Temporary files kept in: {TEMP_DIR}")
        sys.exit(1)


if __name__ == "__main__":
    main()
