
import json
import os
import re
import time
from pathlib import Path

import requests


SCENES_FILE = Path("scenes.json")
VISUALS_DIR = Path("visuals")
CACHE_FILE = Path("visual_cache.json")
OUTPUT_FILE = Path("visuals.json")

PEXELS_API_URL = "https://api.pexels.com/videos/search"
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()

RESULTS_PER_SCENE = 2
MIN_DURATION = 4
MAX_DURATION = 60
MIN_WIDTH = 1280
MIN_HEIGHT = 720
REQUEST_TIMEOUT = 45
DOWNLOAD_TIMEOUT = 120
MAX_SEARCH_PAGES = 2
RETRY_COUNT = 3
RETRY_DELAY = 2

STOCK_SCENE_TYPES = {
    "visual",
    "stock_visual",
    "stock",
    "footage",
    "visual_scene",
}


def load_json(path, default):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Warning: could not read {path}: {exc}")
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    temp_path.replace(path)


def safe_name(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value))
    return value.strip("_") or "scene"


def scene_id_of(scene, index):
    return str(scene.get("scene_id", scene.get("id", index + 1)))


def scene_type_of(scene):
    return str(
        scene.get("type", scene.get("scene_type", "visual"))
    ).strip().lower()


def get_query(scene):
    for key in (
        "visual_query",
        "query",
        "pexels_query",
        "search_query",
    ):
        value = scene.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in (
        "section_title",
        "title",
        "visual_beat",
        "description",
    ):
        value = scene.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return "business person working"


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_timing(scene):
    start = as_float(
        scene.get("start", scene.get("start_time", 0))
    )
    end = as_float(
        scene.get("end", scene.get("end_time", start))
    )
    duration = as_float(
        scene.get("duration", end - start),
        end - start,
    )

    if duration <= 0 and end > start:
        duration = end - start

    return start, end, max(0.0, duration)


def read_existing_scenes():
    data = load_json(OUTPUT_FILE, {})

    if isinstance(data, dict):
        entries = data.get("scenes", [])
    elif isinstance(data, list):
        entries = data
    else:
        entries = []

    result = {}

    for item in entries:
        if isinstance(item, dict) and item.get("scene_id") is not None:
            result[str(item["scene_id"])] = item

    return result


def load_cache():
    data = load_json(CACHE_FILE, {})
    return data if isinstance(data, dict) else {}


def pexels_search(query, cache):
    cache_key = query.casefold().strip()
    cached = cache.get(cache_key)

    if isinstance(cached, dict) and isinstance(
        cached.get("videos"), list
    ):
        print(f"  Using cached search results: {query}")
        return cached["videos"]

    headers = {"Authorization": PEXELS_API_KEY}

    params = {
        "query": query,
        "orientation": "landscape",
        "size": "large",
        "per_page": 30,
        "page": 1,
    }

    results = []
    seen_ids = set()

    for page in range(1, MAX_SEARCH_PAGES + 1):
        params["page"] = page
        response = None

        for attempt in range(1, RETRY_COUNT + 1):
            try:
                response = requests.get(
                    PEXELS_API_URL,
                    headers=headers,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )

                if (
                    response.status_code == 429
                    or response.status_code >= 500
                ):
                    if attempt < RETRY_COUNT:
                        wait = RETRY_DELAY * attempt
                        print(
                            f"  Pexels returned "
                            f"{response.status_code}; retrying "
                            f"in {wait}s..."
                        )
                        time.sleep(wait)
                        continue

                response.raise_for_status()
                break

            except requests.RequestException as exc:
                if attempt == RETRY_COUNT:
                    print(f"  Pexels search failed: {exc}")
                    response = None
                else:
                    wait = RETRY_DELAY * attempt
                    print(
                        f"  Search error; retrying in {wait}s: "
                        f"{exc}"
                    )
                    time.sleep(wait)

        if response is None:
            break

        try:
            payload = response.json()
        except ValueError:
            print("  Pexels returned invalid JSON.")
            break

        page_videos = payload.get("videos", [])

        for video in page_videos:
            video_id = video.get("id")

            if not video_id or video_id in seen_ids:
                continue

            seen_ids.add(video_id)

            duration = as_float(video.get("duration"))

            if duration and not (
                MIN_DURATION <= duration <= MAX_DURATION
            ):
                continue

            candidates = []

            for item in video.get("video_files", []):
                link = item.get("link")
                width = int(item.get("width") or 0)
                height = int(item.get("height") or 0)
                file_type = str(
                    item.get("file_type") or ""
                ).lower()

                if not link:
                    continue

                if file_type and "mp4" not in file_type:
                    continue

                if width <= height:
                    continue

                candidates.append(item)

            if not candidates:
                continue

            candidates.sort(
                key=lambda item: (
                    int(item.get("width") or 0) >= MIN_WIDTH,
                    int(item.get("height") or 0) >= MIN_HEIGHT,
                    int(item.get("width") or 0)
                    * int(item.get("height") or 0),
                ),
                reverse=True,
            )

            best = candidates[0]

            results.append(
                {
                    "pexels_id": video_id,
                    "url": best.get("link"),
                    "width": int(best.get("width") or 0),
                    "height": int(best.get("height") or 0),
                    "duration": duration,
                    "page_url": video.get("url"),
                    "creator": (
                        video.get("user") or {}
                    ).get("name"),
                }
            )

        if not page_videos:
            break

    cache[cache_key] = {
        "videos": results,
        "cached_at": time.time(),
    }

    save_json(CACHE_FILE, cache)
    return results


def download_file(url, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)

    temp_path = destination.with_suffix(
        destination.suffix + ".part"
    )

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            with requests.get(
                url,
                stream=True,
                timeout=DOWNLOAD_TIMEOUT,
            ) as response:
                response.raise_for_status()

                with temp_path.open("wb") as f:
                    for chunk in response.iter_content(
                        chunk_size=1024 * 256
                    ):
                        if chunk:
                            f.write(chunk)

            if (
                not temp_path.exists()
                or temp_path.stat().st_size < 10_000
            ):
                raise OSError(
                    "Downloaded file is empty or too small."
                )

            temp_path.replace(destination)
            return True

        except (requests.RequestException, OSError) as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

            if attempt == RETRY_COUNT:
                print(f"  Download failed: {exc}")
                return False

            wait = RETRY_DELAY * attempt
            print(
                f"  Download error; retrying in {wait}s: {exc}"
            )
            time.sleep(wait)

    return False


def old_scene_is_reusable(
    old_scene,
    query,
    scene_type,
    start,
    end,
):
    old_query = str(
        old_scene.get(
            "visual_query",
            old_scene.get("query", ""),
        )
    ).strip().casefold()

    old_type = str(
        old_scene.get(
            "visual_type",
            old_scene.get("type", "visual"),
        )
    ).strip().lower()

    try:
        old_start = float(old_scene.get("start", -999))
        old_end = float(old_scene.get("end", -999))
    except (TypeError, ValueError):
        return False

    videos = old_scene.get("videos", [])

    if not isinstance(videos, list):
        return False

    if len(videos) < RESULTS_PER_SCENE:
        return False

    # Reuse only if all the old files really exist.
    files_exist = all(
        isinstance(video, dict)
        and video.get("file")
        and Path(video["file"]).is_file()
        for video in videos[:RESULTS_PER_SCENE]
    )

    return (
        old_query == query.strip().casefold()
        and old_type == scene_type
        and abs(old_start - start) < 0.1
        and abs(old_end - end) < 0.1
        and files_exist
    )


def save_progress(final_scenes, remaining_scenes):
    save_json(
        OUTPUT_FILE,
        {
            "source_scenes_file": str(SCENES_FILE),
            "scene_count": len(final_scenes),
            "scenes": final_scenes + remaining_scenes,
        },
    )


def main():
    if not SCENES_FILE.is_file():
        print(
            f"Error: {SCENES_FILE} was not found. "
            "Run scene_detector.py first."
        )
        return 1

    if not PEXELS_API_KEY:
        print(
            "Error: PEXELS_API_KEY is not set.\n"
            "In PowerShell, run:\n"
            '$env:PEXELS_API_KEY = "YOUR_PEXELS_API_KEY"\n'
            "Then run: python download_visuals.py"
        )
        return 1

    scenes_data = load_json(SCENES_FILE, None)

    if isinstance(scenes_data, dict):
        scenes = scenes_data.get("scenes", [])
    elif isinstance(scenes_data, list):
        scenes = scenes_data
    else:
        scenes = []

    if not isinstance(scenes, list) or not scenes:
        print(f"Error: no scenes found in {SCENES_FILE}.")
        return 1

    VISUALS_DIR.mkdir(parents=True, exist_ok=True)

    cache = load_cache()
    existing_scenes = read_existing_scenes()

    # IMPORTANT:
    # Do not reserve IDs from every old scene. Old assignments may
    # belong to an entirely different timeline.
    used_video_ids = set()
    final_scenes = []

    print(f"Loaded {len(scenes)} scenes from {SCENES_FILE}.")

    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            print(f"Skipping invalid scene at index {index}.")
            final_scenes.append(
                {
                    "scene_id": str(index + 1),
                    "type": "unknown",
                    "videos": [],
                }
            )
            continue

        scene_id = scene_id_of(scene, index)
        scene_type = scene_type_of(scene)
        start, end, duration = get_timing(scene)
        query = get_query(scene)

        print(
            f"\n[{index + 1}/{len(scenes)}] "
            f"Scene {scene_id}: {scene_type}, "
            f"{start:.2f}-{end:.2f}s"
        )
        print(f"  Query: {query}")

        metadata = {
            "scene_id": scene_id,
            "type": scene_type,
            "visual_type": scene_type,
            "start": start,
            "end": end,
            "duration": duration,
            "visual_query": query,
            "query": query,
            "videos": [],
        }

        if scene_type not in STOCK_SCENE_TYPES:
            print("  Card/non-stock scene; skipping downloads.")
            final_scenes.append(metadata)
            continue

        old_scene = existing_scenes.get(scene_id)

        if old_scene and old_scene_is_reusable(
            old_scene,
            query,
            scene_type,
            start,
            end,
        ):
            videos = old_scene["videos"][:RESULTS_PER_SCENE]

            # Reserve IDs only for scenes actually being reused.
            for video in videos:
                video_id = video.get("pexels_id")
                if video_id is not None:
                    used_video_ids.add(video_id)

            metadata["videos"] = videos
            print("  Reusing verified footage for unchanged scene.")
            final_scenes.append(metadata)
            continue

        if old_scene:
            print(
                "  Old assignment is stale or incomplete. "
                "Searching again."
            )

        try:
            search_results = pexels_search(query, cache)
        except Exception as exc:
            print(f"  Search failed unexpectedly: {exc}")
            search_results = []

        scene_folder = VISUALS_DIR / (
            f"scene_{safe_name(scene_id)}"
        )
        scene_folder.mkdir(parents=True, exist_ok=True)

        chosen = []

        for result in search_results:
            if len(chosen) >= RESULTS_PER_SCENE:
                break

            video_id = result.get("pexels_id")

            if video_id is None or video_id in used_video_ids:
                continue

            url = result.get("url")
            if not url:
                continue

            destination = scene_folder / f"pexels_{video_id}.mp4"

            if not destination.is_file():
                print(f"  Downloading Pexels video {video_id}...")

                if not download_file(url, destination):
                    continue
            else:
                print(f"  Using existing file: {destination.name}")

            used_video_ids.add(video_id)

            chosen.append(
                {
                    "pexels_id": video_id,
                    "file": str(destination).replace("\\", "/"),
                    "url": result.get("page_url") or url,
                    "creator": result.get("creator"),
                    "width": result.get("width"),
                    "height": result.get("height"),
                    "duration": result.get("duration"),
                }
            )

        metadata["videos"] = chosen
        final_scenes.append(metadata)

        if not chosen:
            print("  WARNING: no footage found for this scene.")
        elif len(chosen) < RESULTS_PER_SCENE:
            print(
                f"  WARNING: only {len(chosen)} of "
                f"{RESULTS_PER_SCENE} videos found."
            )

        # Save the completed assignments plus placeholders for
        # remaining scenes. The next run validates each assignment.
        remaining = []

        for pending_index in range(index + 1, len(scenes)):
            pending = scenes[pending_index]

            if isinstance(pending, dict):
                remaining.append(
                    {
                        "scene_id": scene_id_of(
                            pending, pending_index
                        ),
                        "type": scene_type_of(pending),
                        "videos": [],
                    }
                )

        save_progress(final_scenes, remaining)
        save_json(CACHE_FILE, cache)

    save_json(
        OUTPUT_FILE,
        {
            "source_scenes_file": str(SCENES_FILE),
            "scene_count": len(final_scenes),
            "scenes": final_scenes,
        },
    )
 
    save_json(CACHE_FILE, cache)

    total_videos = sum(
        len(scene.get("videos", []))
        for scene in final_scenes
    )

    stock_scenes = [
        scene
        for scene in final_scenes
        if scene.get("type") in STOCK_SCENE_TYPES
    ]

    scenes_without_footage = [
        scene
        for scene in stock_scenes
        if not scene.get("videos")
    ]

    scenes_with_partial_footage = [
        scene
        for scene in stock_scenes
        if 0 < len(scene.get("videos", [])) < RESULTS_PER_SCENE
    ]

    print()
    print("=" * 60)
    print("VISUAL DOWNLOAD COMPLETE")
    print("=" * 60)
    print(f"Scenes processed: {len(final_scenes)}")
    print(f"Stock footage scenes: {len(stock_scenes)}")
    print(f"Videos downloaded or reused: {total_videos}")
    print(f"Scenes without footage: {len(scenes_without_footage)}")
    print(f"Scenes with partial footage: {len(scenes_with_partial_footage)}")
    print(f"Output metadata: {OUTPUT_FILE.resolve()}")
    print(f"Footage directory: {VISUALS_DIR.resolve()}")

    if scenes_without_footage:
        print()
        print("WARNING: Some stock scenes have no footage:")
        for scene in scenes_without_footage:
            print(
                f"  Scene {scene.get('scene_id')}: "
                f"{scene.get('visual_query', 'unknown query')}"
            )

    if scenes_with_partial_footage:
        print()
        print("WARNING: Some scenes have fewer than "
              f"{RESULTS_PER_SCENE} clips.")

    print()
    print("You can now run create_video.py.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
