import os
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

MUSIC_DIR = "background_music"

TARGET_TRACKS = 30

PAGES = [
    "https://mixkit.co/free-stock-music/ambient/",
    "https://mixkit.co/free-stock-music/ambient/?page=2",
    "https://mixkit.co/free-stock-music/mood/atmospheric/",
    "https://mixkit.co/free-stock-music/mood/calm/",
    "https://mixkit.co/free-stock-music/mood/meditative/",
    "https://mixkit.co/free-stock-music/mood/soothing/",
    "https://mixkit.co/free-stock-music/tag/background/",
    "https://mixkit.co/free-stock-music/tag/documentary/",
    "https://mixkit.co/free-stock-music/tag/technology/",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}


def clean_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip()

    if not name:
        name = "background_music"

    return name[:100]


def existing_music():
    if not os.path.isdir(MUSIC_DIR):
        return []

    files = []

    for name in os.listdir(MUSIC_DIR):
        path = os.path.join(MUSIC_DIR, name)

        if not os.path.isfile(path):
            continue

        if name.lower().endswith(".mp3"):
            files.append(path)

    return files


def find_download_links(html):
    links = []

    # Look for direct Mixkit MP3 URLs.
    patterns = [
        r'https?://assets\.mixkit\.co/music/[^"\']+\.mp3',
        r'https?://assets\.mixkit\.co/[^"\']+\.mp3',
    ]

    for pattern in patterns:
        found = re.findall(pattern, html)

        for url in found:
            url = url.replace("\\/", "/")

            if url not in links:
                links.append(url)

    # Also look inside HTML attributes.
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(True):
        for value in tag.attrs.values():
            if isinstance(value, str):
                found = re.findall(
                    r'https?://assets\.mixkit\.co/[^"\']+\.mp3',
                    value
                )

                for url in found:
                    url = url.replace("\\/", "/")

                    if url not in links:
                        links.append(url)

    return links


def get_page(url):
    print(f"Searching: {url}")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    print(
        f"Page loaded: "
        f"{len(response.text):,} characters"
    )

    return response.text


def download_file(url, path):
    print(f"Downloading: {os.path.basename(path)}")

    response = requests.get(
        url,
        headers=HEADERS,
        stream=True,
        timeout=60
    )

    response.raise_for_status()

    content_type = response.headers.get(
        "Content-Type",
        ""
    ).lower()

    if "audio" not in content_type and not url.lower().endswith(".mp3"):
        print(
            f"Skipped: unexpected content type "
            f"{content_type}"
        )
        return False

    with open(path, "wb") as f:
        for chunk in response.iter_content(
            chunk_size=1024 * 1024
        ):
            if chunk:
                f.write(chunk)

    if not os.path.exists(path):
        return False

    size = os.path.getsize(path)

    if size < 50_000:
        os.remove(path)
        print("Skipped: file is too small.")
        return False

    return True


def get_filename(url, index):
    filename = os.path.basename(
        url.split("?")[0]
    )

    if not filename.lower().endswith(".mp3"):
        filename = f"mixkit_{index}.mp3"

    filename = clean_filename(filename)

    return filename


def main():
    os.makedirs(MUSIC_DIR, exist_ok=True)

    current = existing_music()

    print()
    print("==============================")
    print("MIXKIT MUSIC DOWNLOADER")
    print("==============================")
    print(f"Current tracks: {len(current)}")
    print(f"Target tracks:  {TARGET_TRACKS}")
    print()

    if len(current) >= TARGET_TRACKS:
        print("Music library already has enough tracks.")
        print(
            f"Folder: {os.path.abspath(MUSIC_DIR)}"
        )
        return

    downloaded = 0
    discovered = set()
    existing_names = {
        os.path.basename(x).lower()
        for x in current
    }

    for page in PAGES:

        if len(current) + downloaded >= TARGET_TRACKS:
            break

        try:
            html = get_page(page)

        except Exception as e:
            print(f"Page failed: {e}")
            print()
            continue

        links = find_download_links(html)

        print(
            f"Direct MP3 links found: {len(links)}"
        )

        for url in links:

            if len(current) + downloaded >= TARGET_TRACKS:
                break

            if url in discovered:
                continue

            discovered.add(url)

            filename = get_filename(
                url,
                downloaded + 1
            )

            if filename.lower() in existing_names:
                continue

            path = os.path.join(
                MUSIC_DIR,
                filename
            )

            try:
                if download_file(url, path):
                    downloaded += 1
                    existing_names.add(
                        filename.lower()
                    )

                    print(
                        f"Downloaded "
                        f"{downloaded}/{TARGET_TRACKS - len(current)}"
                    )

            except Exception as e:
                print(
                    f"Download failed: {e}"
                )

                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

            time.sleep(0.3)

        print()

    final_tracks = existing_music()

    print()
    print("==============================")
    print("DOWNLOAD COMPLETE")
    print("==============================")
    print(f"New tracks:   {downloaded}")
    print(f"Total tracks: {len(final_tracks)}")
    print()
    print(
        f"Music folder:\n"
        f"{os.path.abspath(MUSIC_DIR)}"
    )
    print()

    if len(final_tracks) < TARGET_TRACKS:
        print(
            "Not enough tracks were found."
        )
        print(
            "Run the script again to try the remaining pages."
        )
    else:
        print(
            "Music library is ready for add_music.py."
        )


if __name__ == "__main__":
    main()
