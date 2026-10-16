import os
import re
import json
import time
import shutil
import hashlib
import subprocess
from pathlib import Path

import requests


BASE_DIR = Path(r"C:\Users\Phuc\Desktop\AI_Faceless_Channel")

SCENES_FILE = BASE_DIR / "scenes.json"
ASSET_DIR = BASE_DIR / "visual_assets"
CACHE_DIR = BASE_DIR / "pexels_cache"
OUTPUT_FILE = BASE_DIR / "final_video.mp4"

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/videos/search"

WIDTH = 1920
HEIGHT = 1080
FPS = 30

PER_PAGE = 40
SEARCH_DELAY = 0.35

MIN_SOURCE_DURATION = 3
MAX_SOURCE_DURATION = 120

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def run_cmd(cmd):
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}"
        )

    return result


def clean_query(query):
    query = str(query or "").strip().lower()
    query = re.sub(r"\s+", " ", query)
    return query


def safe_name(text):
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", text)
    return text[:100]


def query_hash(query):
    return hashlib.sha1(
        clean_query(query).encode("utf-8")
    ).hexdigest()


def ensure_dirs():
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_scenes():
    if not SCENES_FILE.exists():
        raise FileNotFoundError(
            f"Missing scenes.json:\n{SCENES_FILE}"
        )

    with open(
        SCENES_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    if isinstance(data, dict):
        scenes = data.get("scenes")
    else:
        scenes = data

    if not isinstance(scenes, list):
        raise ValueError(
            "scenes.json does not contain a scenes list"
        )

    if not scenes:
        raise ValueError("scenes.json contains no scenes")

    return scenes


def probe_duration(path):
    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]

    result = run_cmd(cmd)

    try:
        return float(result.stdout.strip())
    except:
        raise RuntimeError(
            f"Could not determine duration of {path}"
        )


def probe_video(path):
    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,duration",
        "-of",
        "json",
        str(path)
    ]

    result = run_cmd(cmd)

    try:
        data = json.loads(result.stdout)
        stream = data["streams"][0]

        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))

        duration = stream.get("duration")

        if duration is None:
            duration = probe_duration(path)

        return {
            "width": width,
            "height": height,
            "duration": float(duration)
        }

    except Exception as e:
        raise RuntimeError(
            f"Could not inspect video {path}: {e}"
        )


def choose_video_file(video):
    files = video.get("video_files", [])

    if not files:
        return None

    candidates = []

    for item in files:
        link = item.get("link")
        width = item.get("width") or 0
        height = item.get("height") or 0
        quality = item.get("quality", "")

        if not link:
            continue

        if width < 1280 or height < 720:
            continue

        if height == 0 or width == 0:
            continue

        ratio = width / height

        if ratio < 1.5:
            continue

        candidates.append({
            "link": link,
            "width": width,
            "height": height,
            "quality": quality
        })

    if not candidates:
        for item in files:
            link = item.get("link")

            if link:
                candidates.append({
                    "link": link,
                    "width": item.get("width") or 0,
                    "height": item.get("height") or 0,
                    "quality": item.get("quality", "")
                })

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: (
            x["width"] * x["height"],
            x["width"]
        ),
        reverse=True
    )

    for item in candidates:
        if item["width"] >= 1920:
            return item

    return candidates[0]


def search_pexels(query):
    query = clean_query(query)

    if not query:
        raise ValueError("Empty Pexels query")

    cache_file = CACHE_DIR / f"{query_hash(query)}.json"

    if cache_file.exists():
        try:
            with open(
                cache_file,
                "r",
                encoding="utf-8"
            ) as f:
                cached = json.load(f)

            if isinstance(cached, dict):
                return cached
        except:
            pass

    if not PEXELS_API_KEY:
        raise RuntimeError(
            "PEXELS_API_KEY environment variable is missing.\n"
            "Set it before running the script."
        )

    headers = {
        "Authorization": PEXELS_API_KEY
    }

    params = {
        "query": query,
        "orientation": "landscape",
        "size": "large",
        "locale": "en-US",
        "page": 1,
        "per_page": PER_PAGE
    }

    print(f"  Searching Pexels: {query}")

    response = requests.get(
        PEXELS_SEARCH_URL,
        headers=headers,
        params=params,
        timeout=60
    )

    if response.status_code == 429:
        raise RuntimeError(
            "Pexels rate limit reached. "
            "Try again later."
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"Pexels API error {response.status_code}: "
            f"{response.text[:1000]}"
        )

    data = response.json()

    with open(
        cache_file,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )

    time.sleep(SEARCH_DELAY)

    return data


def get_candidates(query):
    data = search_pexels(query)

    videos = data.get("videos", [])

    candidates = []

    for video in videos:
        duration = float(
            video.get("duration") or 0
        )

        if duration < MIN_SOURCE_DURATION:
            continue

        if duration > MAX_SOURCE_DURATION:
            continue

        chosen = choose_video_file(video)

        if not chosen:
            continue

        candidates.append({
            "id": video.get("id"),
            "duration": duration,
            "width": chosen["width"],
            "height": chosen["height"],
            "link": chosen["link"],
            "pexels_url": video.get("url"),
            "user_name": (
                video.get("user", {})
                .get("name")
            ),
            "user_url": (
                video.get("user", {})
                .get("url")
            )
        })

    return candidates


def get_asset_path(scene_id):
    return ASSET_DIR / f"scene_{scene_id:03d}.mp4"


def get_metadata_path(scene_id):
    return ASSET_DIR / f"scene_{scene_id:03d}.json"


def download_file(url, output):
    temp = output.with_suffix(".download")

    if temp.exists():
        temp.unlink()

    with requests.get(
        url,
        stream=True,
        timeout=120
    ) as response:

        if response.status_code != 200:
            raise RuntimeError(
                f"Video download failed "
                f"{response.status_code}: {url}"
            )

        with open(temp, "wb") as f:
            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):
                if chunk:
                    f.write(chunk)

    temp.replace(output)


def select_video(
    scene,
    used_ids,
    scene_index
):
    query = clean_query(
        scene.get("query", "")
    )

    if not query:
        raise ValueError(
            f"Scene {scene.get('id')} has no query"
        )

    candidates = get_candidates(query)

    if not candidates:
        fallback_queries = [
            "business technology",
            "entrepreneur laptop",
            "modern office",
            "startup technology",
            "computer work"
        ]

        for fallback in fallback_queries:
            if fallback == query:
                continue

            print(
                f"  No suitable results. "
                f"Trying: {fallback}"
            )

            candidates = get_candidates(fallback)

            if candidates:
                break

    if not candidates:
        raise RuntimeError(
            f"No usable Pexels videos found for:\n{query}"
        )

    fresh = [
        x for x in candidates
        if x["id"] not in used_ids
    ]

    if not fresh:
        fresh = candidates

    target_duration = (
        float(scene["end"])
        - float(scene["start"])
    )

    def score(item):
        duration = item["duration"]

        if duration >= target_duration:
            duration_score = min(
                duration - target_duration,
                30
            )
        else:
            duration_score = (
                target_duration - duration
            ) * 2

        resolution_score = 0

        if item["width"] >= 1920:
            resolution_score -= 5

        if item["height"] >= 1080:
            resolution_score -= 5

        return duration_score + resolution_score

    fresh.sort(key=score)

    return fresh[0]


def prepare_source(
    source_path,
    output_path,
    duration
):
    source_duration = probe_duration(source_path)

    if source_duration <= 0:
        raise RuntimeError(
            f"Invalid source duration: {source_path}"
        )

    if source_duration >= duration:
        start = 0.0

        if source_duration > duration + 1:
            max_start = source_duration - duration

            seed = int(
                hashlib.md5(
                    str(output_path).encode()
                ).hexdigest()[:8],
                16
            )

            start = (
                seed / 0xFFFFFFFF
            ) * max_start

        cmd = [
            FFMPEG,
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(source_path),
            "-t",
            f"{duration:.3f}",
            "-vf",
            (
                "scale=1920:1080:"
                "force_original_aspect_ratio=increase,"
                "crop=1920:1080"
            ),
            "-r",
            str(FPS),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(output_path)
        ]

        run_cmd(cmd)
        return

    loops = int(
        duration / source_duration
    ) + 1

    cmd = [
        FFMPEG,
        "-y",
        "-stream_loop",
        str(loops),
        "-i",
        str(source_path),
        "-t",
        f"{duration:.3f}",
        "-vf",
        (
            "scale=1920:1080:"
            "force_original_aspect_ratio=increase,"
            "crop=1920:1080"
        ),
        "-r",
        str(FPS),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        str(output_path)
    ]

    run_cmd(cmd)


def process_scene(
    scene,
    used_ids,
    scene_index
):
    scene_id = int(scene["id"])

    start = float(scene["start"])
    end = float(scene["end"])
    duration = end - start

    if duration <= 0:
        raise ValueError(
            f"Scene {scene_id} has invalid duration"
        )

    output_path = get_asset_path(scene_id)
    metadata_path = get_metadata_path(scene_id)

    if output_path.exists():
        try:
            existing_duration = probe_duration(
                output_path
            )

            if abs(existing_duration - duration) < 0.15:
                print(
                    f"[{scene_id}] Reusing existing asset"
                )

                if metadata_path.exists():
                    try:
                        with open(
                            metadata_path,
                            "r",
                            encoding="utf-8"
                        ) as f:
                            metadata = json.load(f)

                        if metadata.get("pexels_id"):
                            used_ids.add(
                                metadata["pexels_id"]
                            )
                    except:
                        pass

                return output_path

        except:
            pass

        output_path.unlink()

    print()
    print(
        f"[{scene_id}] "
        f"{start:.2f}s -> {end:.2f}s "
        f"({duration:.2f}s)"
    )
    print(
        f"  Query: {scene.get('query')}"
    )

    selected = select_video(
        scene,
        used_ids,
        scene_index
    )

    pexels_id = selected["id"]

    print(
        f"  Selected Pexels video: {pexels_id}"
    )

    raw_path = (
        ASSET_DIR /
        f"raw_{scene_id:03d}_{pexels_id}.mp4"
    )

    if not raw_path.exists():
        print("  Downloading...")
        download_file(
            selected["link"],
            raw_path
        )

    print("  Rendering scene...")

    prepare_source(
        raw_path,
        output_path,
        duration
    )

    metadata = {
        "scene_id": scene_id,
        "start": start,
        "end": end,
        "duration": duration,
        "query": scene.get("query"),
        "type": scene.get("type"),
        "section": scene.get("section"),
        "title": scene.get("title"),
        "pexels_id": pexels_id,
        "pexels_url": selected["pexels_url"],
        "photographer": selected["user_name"],
        "photographer_url": selected["user_url"],
        "source_video_url": selected["link"]
    }

    with open(
        metadata_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            metadata,
            f,
            indent=2,
            ensure_ascii=False
        )

    used_ids.add(pexels_id)

    return output_path


def create_concat_file(scene_files):
    concat_file = ASSET_DIR / "concat.txt"

    with open(
        concat_file,
        "w",
        encoding="utf-8"
    ) as f:
        for path in scene_files:
            normalized = str(path.resolve())
            normalized = normalized.replace(
                "\\",
                "/"
            )
            normalized = normalized.replace(
                "'",
                "'\\''"
            )

            f.write(
                f"file '{normalized}'\n"
            )

    return concat_file


def build_final_video(scene_files):
    concat_file = create_concat_file(
        scene_files
    )

    temp_output = (
        BASE_DIR /
        "final_video_building.mp4"
    )

    if temp_output.exists():
        temp_output.unlink()

    cmd = [
        FFMPEG,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        "-an",
        str(temp_output)
    ]

    print()
    print("Combining scenes...")
    run_cmd(cmd)

    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()

    temp_output.replace(OUTPUT_FILE)

    return OUTPUT_FILE


def verify_final_video(
    scenes,
    output_path
):
    actual_duration = probe_duration(
        output_path
    )

    expected_duration = float(
        scenes[-1]["end"]
    )

    difference = abs(
        actual_duration - expected_duration
    )

    print()
    print("FINAL VIDEO")
    print("-" * 60)
    print(
        f"Expected: {expected_duration:.3f}s"
    )
    print(
        f"Actual:   {actual_duration:.3f}s"
    )
    print(
        f"Difference: {difference:.3f}s"
    )
    print(
        f"File: {output_path}"
    )

    if difference > 0.20:
        raise RuntimeError(
            "Final video duration differs from "
            "scene timeline by more than 0.20s"
        )


def write_attribution(scenes):
    attribution_file = (
        BASE_DIR /
        "pexels_attribution.txt"
    )

    seen = set()
    entries = []

    for scene in scenes:
        metadata_path = get_metadata_path(
            int(scene["id"])
        )

        if not metadata_path.exists():
            continue

        try:
            with open(
                metadata_path,
                "r",
                encoding="utf-8"
            ) as f:
                metadata = json.load(f)
        except:
            continue

        pexels_id = metadata.get(
            "pexels_id"
        )

        if pexels_id in seen:
            continue

        seen.add(pexels_id)

        photographer = (
            metadata.get("photographer")
            or "Unknown photographer"
        )

        photographer_url = (
            metadata.get("photographer_url")
            or ""
        )

        pexels_url = (
            metadata.get("pexels_url")
            or ""
        )

        entries.append(
            {
                "id": pexels_id,
                "photographer": photographer,
                "photographer_url": photographer_url,
                "pexels_url": pexels_url
            }
        )

    with open(
        attribution_file,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(
            "Visual footage provided by Pexels.\n\n"
        )

        for item in entries:
            f.write(
                f"Pexels video {item['id']}\n"
            )
            f.write(
                f"Photographer: "
                f"{item['photographer']}\n"
            )

            if item["photographer_url"]:
                f.write(
                    f"Photographer URL: "
                    f"{item['photographer_url']}\n"
                )

            if item["pexels_url"]:
                f.write(
                    f"Pexels URL: "
                    f"{item['pexels_url']}\n"
                )

            f.write("\n")

    return attribution_file


def main():
    print("=" * 70)
    print("AI FACELESS CHANNEL - VISUAL BUILDER")
    print("=" * 70)

    ensure_dirs()

    scenes = load_scenes()

    print(
        f"Loaded {len(scenes)} scenes"
    )

    scenes.sort(
        key=lambda x: float(x["start"])
    )

    expected_start = 0.0

    for scene in scenes:
        start = float(scene["start"])
        end = float(scene["end"])

        if abs(start - expected_start) > 0.05:
            raise ValueError(
                f"Timeline gap/overlap before "
                f"scene {scene['id']}: "
                f"{expected_start:.3f} -> {start:.3f}"
            )

        if end <= start:
            raise ValueError(
                f"Invalid scene {scene['id']}"
            )

        expected_start = end

    print(
        f"Timeline: 0.00 -> "
        f"{expected_start:.2f}s"
    )

    used_ids = set()
    scene_files = []

    for index, scene in enumerate(
        scenes,
        start=1
    ):
        path = process_scene(
            scene,
            used_ids,
            index
        )

        scene_files.append(path)

    print()
    print(
        f"All {len(scene_files)} scene assets ready."
    )

    final_path = build_final_video(
        scene_files
    )

    verify_final_video(
        scenes,
        final_path
    )

    attribution = write_attribution(
        scenes
    )

    print()
    print("=" * 70)
    print("DONE")
    print("=" * 70)
    print(
        f"Final video: {final_path}"
    )
    print(
        f"Attribution: {attribution}"
    )
    print()
    print(
        "Pexels attribution should be included "
        "with the published video/project."
    )


if __name__ == "__main__":
    main()
