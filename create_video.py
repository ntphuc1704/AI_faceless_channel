import os
import sys
import subprocess
import time


SCRIPTS = [
    ("Research", "research.py"),
    ("Voice generation", "voice.py"),
    ("Scene detection", "scene_detector.py"),
    ("Visual download", "download_visuals.py"),
    ("Video creation with subtitles", "make_videos.py"),
    ("Background music", "add_music.py"),
]


def run_step(name, script):
    print()
    print("=" * 70)
    print(name.upper())
    print("=" * 70)
    print(f"Running: {script}")
    print()

    start = time.time()

    result = subprocess.run(
        [sys.executable, script],
        stdin=None,
    )

    elapsed = time.time() - start

    if result.returncode != 0:
        print()
        print("=" * 70)
        print(f"{name.upper()} FAILED")
        print("=" * 70)
        print(f"Script: {script}")
        print(f"Exit code: {result.returncode}")
        print(f"Time: {elapsed:.1f}s")
        print()
        return False

    print()
    print(f"{name} completed successfully.")
    print(f"Time: {elapsed:.1f}s")
    return True


def check_file(path, name):
    if not os.path.exists(path):
        print()
        print(f"ERROR: {name} was not created:")
        print(os.path.abspath(path))
        return False

    size = os.path.getsize(path)
    if size < 100_000:
        print()
        print(f"ERROR: {name} is suspiciously small:")
        print(f"Size: {size} bytes")
        return False

    return True


def main():
    print()
    print("=" * 70)
    print("AI FACELESS VIDEO CREATOR")
    print("=" * 70)
    print()
    print("This will run the complete video pipeline.")
    print("Subtitles are burned into the video by make_videos.py.")
    print("The separate add_subtitles.py step is intentionally disabled.")
    print()

    for name, script in SCRIPTS:
        if not os.path.exists(script):
            print(f"ERROR: Missing script: {script}")
            print()
            return 1

    total_start = time.time()

    for name, script in SCRIPTS:
        if not run_step(name, script):
            print()
            print("=" * 70)
            print("VIDEO CREATION STOPPED")
            print("=" * 70)
            print()
            print("Nothing was cleaned up.")
            print("You can inspect the generated files and fix the problem.")
            print()
            return 1

    print()
    print("=" * 70)
    print("VERIFYING FINAL VIDEO")
    print("=" * 70)
    print()

    if not check_file("final_video.mp4", "final_video.mp4"):
        print()
        print("Video creation failed verification.")
        print("Nothing was cleaned up.")
        print()
        return 1

    total_time = time.time() - total_start
    size_mb = os.path.getsize("final_video.mp4") / (1024 * 1024)

    print()
    print("=" * 70)
    print("VIDEO CREATED SUCCESSFULLY")
    print("=" * 70)
    print()
    print(f"File: {os.path.abspath('final_video.mp4')}")
    print(f"Size: {size_mb:.2f} MB")
    print(f"Total time: {total_time / 60:.1f} minutes")
    print()
    print("The video is ready for upload.")
    print("Narration, title typing sounds, rolling subtitles, and background music are included.")
    print("Subtitles should be hidden during the white rolling-text section cards.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
