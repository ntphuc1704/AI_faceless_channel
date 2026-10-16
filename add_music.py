import os
import random
import shutil
import subprocess

VIDEO_FILE = "final_video.mp4"
MUSIC_DIR = "background_music"
TEMP_DIR = "music_temp"
OUTPUT_FILE = os.path.join(TEMP_DIR, "final_video.mp4")

MUSIC_VOLUME = 0.07


def run(cmd):
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    print(result.stdout)

    if result.returncode != 0:
        raise RuntimeError("FFmpeg failed.")


def find_music():
    if not os.path.isdir(MUSIC_DIR):
        return []

    files = []

    for name in os.listdir(MUSIC_DIR):
        path = os.path.join(MUSIC_DIR, name)

        if not os.path.isfile(path):
            continue

        ext = os.path.splitext(name)[1].lower()

        if ext in [".mp3", ".wav", ".m4a", ".aac", ".ogg"]:
            files.append(path)

    return files


def main():
    if not os.path.exists(VIDEO_FILE):
        print(f"ERROR: {VIDEO_FILE} not found.")
        return

    music_files = find_music()

    if not music_files:
        print("ERROR: No background music found.")
        print()
        print(f"Put music files inside:")
        print(os.path.abspath(MUSIC_DIR))
        return

    music = random.choice(music_files)

    print()
    print("================================")
    print("ADDING BACKGROUND MUSIC")
    print("================================")
    print(f"Video: {VIDEO_FILE}")
    print(f"Music: {os.path.basename(music)}")
    print(f"Volume: {MUSIC_VOLUME * 100:.0f}%")
    print("================================")
    print()

    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)

    os.makedirs(TEMP_DIR)

    try:
        run([
            "ffmpeg",
            "-y",
            "-i",
            VIDEO_FILE,
            "-stream_loop",
            "-1",
            "-i",
            music,
            "-filter_complex",
            f"[1:a]volume={MUSIC_VOLUME}[music];"
            "[0:a][music]amix="
            "inputs=2:"
            "duration=first:"
            "dropout_transition=3[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            OUTPUT_FILE
        ])

        if not os.path.exists(OUTPUT_FILE):
            raise RuntimeError("Output video was not created.")

        if os.path.getsize(OUTPUT_FILE) < 100000:
            raise RuntimeError("Output video is suspiciously small.")

        os.replace(OUTPUT_FILE, VIDEO_FILE)

        shutil.rmtree(TEMP_DIR, ignore_errors=True)

        print()
        print("================================")
        print("BACKGROUND MUSIC ADDED")
        print("================================")
        print(f"Output: {VIDEO_FILE}")
        print(f"Music: {os.path.basename(music)}")
        print(f"Volume: {MUSIC_VOLUME * 100:.0f}%")
        print("================================")

    except Exception as e:
        print()
        print("ERROR:")
        print(e)
        print()
        print("The original video was NOT replaced.")
        print(f"Temporary files kept in: {TEMP_DIR}")


if __name__ == "__main__":
    main()
