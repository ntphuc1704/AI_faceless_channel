
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONTENT_FILE = BASE_DIR / "content.txt"
OUTPUT_FILE = BASE_DIR / "voice.wav"
SEGMENTS_FILE = BASE_DIR / "voice_segments.json"

VOICE = "en-US-AndrewMultilingualNeural"

EXPECTED_CHAPTERS = 7

PROFILES = {
    "normal": {"rate": "-3%", "volume": "+0%"},
    "slightly_slow": {"rate": "-7%", "volume": "+1%"},
    "slow": {"rate": "-12%", "volume": "+4%"},
    "strong": {"rate": "-8%", "volume": "+8%"},
    "very_strong": {"rate": "-12%", "volume": "+10%"},
    "fast": {"rate": "+5%", "volume": "+0%"},
    "excited": {"rate": "+8%", "volume": "+4%"},
    "quiet": {"rate": "-5%", "volume": "-5%"},
}

MARKER_PATTERN = re.compile(
    r"^\s*//\s*(INTRO|OUTRO|([1-5])\.\s*(.+?))\s*$",
    re.IGNORECASE,
)


def clean_text(text):
    text = text.replace("\ufeff", " ")
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_into_sentences(text):
    text = clean_text(text)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def parse_script(raw_text):
    """
    Parse chapter markers and narration from content.txt.

    Expected marker order:
        // INTRO
        // 1. Chapter title
        // 2. Chapter title
        // 3. Chapter title
        // 4. Chapter title
        // 5. Chapter title
        // OUTRO

    Marker text is metadata and is never sent to Edge TTS.
    """
    chapters = []
    current_chapter = None

    for line_number, line in enumerate(raw_text.splitlines(), 1):
        match = MARKER_PATTERN.match(line)

        if match:
            marker_text = match.group(1).strip()
            number = match.group(2)
            title = match.group(3)

            if marker_text.upper() == "INTRO":
                chapter_type = "intro"
                marker = "INTRO"
                title = "Introduction"
                display_title = "INTRO"
            elif marker_text.upper() == "OUTRO":
                chapter_type = "outro"
                marker = "OUTRO"
                title = "Conclusion"
                display_title = "OUTRO"
            else:
                chapter_type = "section"
                marker = f"{number}"
                title = clean_text(title)
                display_title = f"{int(number):02d} — {title}"

            current_chapter = {
                "id": len(chapters) + 1,
                "type": chapter_type,
                "marker": marker,
                "title": title,
                "display_title": display_title,
                "marker_line": line_number,
                "text_parts": [],
            }
            chapters.append(current_chapter)
            continue

        if line.strip():
            if current_chapter is None:
                raise ValueError(
                    f"Narration found before the first chapter marker "
                    f"at line {line_number}. Add // INTRO at the beginning."
                )

            current_chapter["text_parts"].append(line.strip())

    if len(chapters) != EXPECTED_CHAPTERS:
        found = [chapter["display_title"] for chapter in chapters]
        raise ValueError(
            f"Expected exactly {EXPECTED_CHAPTERS} chapter markers, "
            f"but found {len(chapters)}.\n"
            f"Markers found: {found}\n"
            "Required order: // INTRO, // 1. Title through // 5. Title, // OUTRO."
        )

    if chapters[0]["type"] != "intro":
        raise ValueError("The first chapter marker must be // INTRO.")

    if chapters[-1]["type"] != "outro":
        raise ValueError("The final chapter marker must be // OUTRO.")

    for index, chapter in enumerate(chapters[1:6], 1):
        if chapter["type"] != "section" or chapter["marker"] != str(index):
            raise ValueError(
                f"Expected // {index}. Title at chapter position {index + 1}, "
                f"but found {chapter['display_title']}."
            )

    for chapter in chapters:
        chapter_text = clean_text(" ".join(chapter["text_parts"]))
        chapter["sentences"] = split_into_sentences(chapter_text)

        del chapter["text_parts"]

        if not chapter["sentences"]:
            raise ValueError(
                f"Chapter '{chapter['display_title']}' has no narration."
            )

    return chapters


def detect_profile(sentence):
    s = sentence.lower().strip()
    words = len(sentence.split())

    strong_phrases = [
        "most importantly", "the real reason", "here's the catch",
        "the catch", "this matters", "pay attention", "don't forget",
        "the biggest", "the most important", "be careful",
    ]
    strong_words = [
        "important", "critical", "especially", "remember", "warning",
    ]
    excitement_words = [
        "huge", "massive", "powerful", "amazing", "incredible",
        "surprisingly", "seriously", "actually", "potential", "opportunity",
    ]
    transition_words = [
        "however", "but", "instead", "although", "meanwhile",
        "on the other hand", "beyond that", "another", "finally",
        "more importantly",
    ]

    if any(phrase in s for phrase in strong_phrases):
        return "very_strong"

    if any(
        re.search(rf"\b{re.escape(word)}\b", s)
        for word in strong_words
    ):
        return "very_strong"

    if any(
        re.search(rf"\b{re.escape(word)}\b", s)
        for word in excitement_words
    ):
        return "excited"

    if any(
        re.search(rf"\b{re.escape(word)}\b", s)
        for word in transition_words
    ):
        return "strong"

    if words <= 6 and ("!" in sentence or "?" in sentence):
        return "excited"

    if words >= 50:
        return "slow"

    if words >= 35:
        return "slightly_slow"

    return "normal"


def get_audio_duration(filename, ffprobe):
    command = [
        ffprobe,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(filename),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed for {filename}: {result.stderr.strip()}"
        )

    try:
        duration = float(result.stdout.strip())
    except (TypeError, ValueError):
        raise RuntimeError(
            f"Could not read audio duration for {filename}."
        )

    if duration <= 0:
        raise RuntimeError(
            f"Invalid audio duration for {filename}: {duration}"
        )

    return duration


def run_command(command, label):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"{label} failed:\n{result.stderr[-10000:]}"
        )

    return result


async def generate_audio(text, output_file, profile):
    import edge_tts

    communicate = edge_tts.Communicate(
        text,
        VOICE,
        rate=profile["rate"],
        volume=profile["volume"],
    )

    await communicate.save(str(output_file))


def atomic_write_json(path, data):
    temp_path = path.with_name(path.name + ".tmp")

    try:
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)

        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


async def main():
    if not CONTENT_FILE.is_file():
        raise FileNotFoundError(
            f"Required script not found: {CONTENT_FILE.resolve()}"
        )

    raw_text = CONTENT_FILE.read_text(encoding="utf-8-sig")

    if not raw_text.strip():
        raise ValueError("content.txt is empty.")

    chapters = parse_script(raw_text)

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if not ffmpeg or not ffprobe:
        raise RuntimeError(
            "FFmpeg and FFprobe must both be available in PATH."
        )

    sentence_jobs = []

    for chapter in chapters:
        for sentence in chapter["sentences"]:
            sentence_jobs.append({
                "chapter_id": chapter["id"],
                "chapter_type": chapter["type"],
                "chapter_marker": chapter["marker"],
                "chapter_title": chapter["title"],
                "display_title": chapter["display_title"],
                "text": sentence,
            })

    if not sentence_jobs:
        raise ValueError("No narration sentences were found.")

    print(f"Script: {CONTENT_FILE.resolve()}")
    print(f"Voice: {VOICE}")
    print(f"Chapters: {len(chapters)}")
    print(f"Sentences to generate: {len(sentence_jobs)}")
    print("\nChapter markers:")

    for chapter in chapters:
        print(
            f"  {chapter['display_title']} "
            f"({len(chapter['sentences'])} sentences)"
        )

    print(
        "\nChapter markers will not be spoken. "
        "Every narration sentence must succeed.\n"
    )

    # Store temporary files beside the outputs so replacements remain
    # on the same filesystem. The temporary directory is automatically
    # removed when generation finishes or raises an error.
    with tempfile.TemporaryDirectory(
        prefix="edge_tts_",
        dir=str(BASE_DIR),
    ) as temp_name:
        temp_dir = Path(temp_name)
        audio_files = []
        segments = []
        current_time = 0.0

        chapter_times = {
            chapter["id"]: {
                "start": None,
                "end": None,
                "sentence_count": 0,
            }
            for chapter in chapters
        }

        for i, job in enumerate(sentence_jobs, 1):
            sentence = job["text"]
            profile_name = detect_profile(sentence)
            profile = PROFILES[profile_name]
            audio_path = temp_dir / f"part_{i:04d}.mp3"

            print(
                f"[{i}/{len(sentence_jobs)}] "
                f"[{job['display_title']}] {profile_name}: "
                f"{sentence[:100]}"
                f"{'...' if len(sentence) > 100 else ''}"
            )

            try:
                await generate_audio(sentence, audio_path, profile)
            except Exception as exc:
                raise RuntimeError(
                    f"Edge TTS failed on sentence {i}/{len(sentence_jobs)}. "
                    "No new voice.wav was installed.\n"
                    f"Chapter: {job['display_title']}\n"
                    f"Sentence: {sentence}\n"
                    f"Error: {exc}"
                ) from exc

            if not audio_path.is_file() or audio_path.stat().st_size < 100:
                raise RuntimeError(
                    f"Sentence {i}/{len(sentence_jobs)} produced a missing "
                    "or tiny audio file. No new voice.wav was installed.\n"
                    f"Sentence: {sentence}"
                )

            duration = get_audio_duration(audio_path, ffprobe)
            start_time = current_time
            end_time = start_time + duration

            chapter_time = chapter_times[job["chapter_id"]]

            if chapter_time["start"] is None:
                chapter_time["start"] = round(start_time, 3)

            chapter_time["end"] = round(end_time, 3)
            chapter_time["sentence_count"] += 1

            segments.append({
                "id": i,
                "text": sentence,
                "profile": profile_name,
                "chapter_id": job["chapter_id"],
                "chapter_type": job["chapter_type"],
                "chapter_marker": job["chapter_marker"],
                "chapter_title": job["chapter_title"],
                "display_title": job["display_title"],
                "start": round(start_time, 3),
                "end": round(end_time, 3),
                "duration": round(duration, 3),
            })

            current_time = end_time
            audio_files.append(audio_path)

        if len(audio_files) != len(sentence_jobs):
            raise RuntimeError(
                f"Expected {len(sentence_jobs)} audio files, "
                f"but generated {len(audio_files)}."
            )

        concat_file = temp_dir / "concat.txt"

        with concat_file.open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as file:
            for audio_path in audio_files:
                normalized = str(audio_path.resolve()).replace("\\", "/")
                normalized = normalized.replace("'", "'\\''")
                file.write(f"file '{normalized}'\n")

        temp_voice = temp_dir / "voice_new.wav"

        run_command([
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-vn",
            "-ar", "44100",
            "-ac", "2",
            "-c:a", "pcm_s16le",
            str(temp_voice),
        ], "FFmpeg audio concatenation")

        if not temp_voice.is_file() or temp_voice.stat().st_size < 1000:
            raise RuntimeError(
                "FFmpeg did not produce a valid replacement voice.wav."
            )

        final_duration = get_audio_duration(temp_voice, ffprobe)

        if abs(final_duration - current_time) > max(
            2.0,
            len(sentence_jobs) * 0.03,
        ):
            raise RuntimeError(
                "Audio duration validation failed. "
                f"Sum of sentence durations: {current_time:.2f}s; "
                f"combined WAV duration: {final_duration:.2f}s. "
                "The old voice.wav has been preserved."
            )

        chapter_records = []

        for chapter in chapters:
            timing = chapter_times[chapter["id"]]

            if timing["start"] is None or timing["end"] is None:
                raise RuntimeError(
                    f"No timing was recorded for "
                    f"{chapter['display_title']}."
                )

            chapter_records.append({
                "id": chapter["id"],
                "type": chapter["type"],
                "marker": chapter["marker"],
                "title": chapter["title"],
                "display_title": chapter["display_title"],
                "start": timing["start"],
                "end": timing["end"],
                "duration": round(
                    timing["end"] - timing["start"], 3
                ),
                "sentence_count": timing["sentence_count"],
            })

        data = {
            "voice": VOICE,
            "source_file": str(CONTENT_FILE),
            "source_characters": len(raw_text),
            "source_sentence_count": len(sentence_jobs),
            "generated_sentence_count": len(segments),
            "chapter_count": len(chapter_records),
            "total_duration": round(final_duration, 3),
            "chapters": chapter_records,
            "segments": segments,
        }

        temp_segments = temp_dir / "voice_segments_new.json"
        temp_segments.write_text(
            json.dumps(data, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )

        # Preserve the previous files until generation and validation pass.
        # Install the new audio first, then the corresponding metadata.
        os.replace(temp_voice, OUTPUT_FILE)
        os.replace(temp_segments, SEGMENTS_FILE)

    print("\nVoice generation completed and validated.")
    print(f"Created: {OUTPUT_FILE.resolve()}")
    print(f"Created: {SEGMENTS_FILE.resolve()}")
    print(f"Generated sentences: {len(segments)}")
    print(f"Audio duration: {final_duration:.2f} seconds")

    print("\nChapter timings:")

    for chapter in chapter_records:
        print(
            f"  {chapter['display_title']}: "
            f"{chapter['start']:.2f}s - {chapter['end']:.2f}s"
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"\nVOICE GENERATION ABORTED: {exc}")
        raise SystemExit(1)

