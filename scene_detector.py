import os
import re
import json
import math
import time
import requests
from difflib import SequenceMatcher


BASE_DIR = r"C:\Users\Phuc\Desktop\AI_Faceless_Channel"

VOICE_FILE = os.path.join(BASE_DIR, "voice_segments.json")
CONTENT_FILE = os.path.join(BASE_DIR, "content.txt")
OUTPUT_FILE = os.path.join(BASE_DIR, "scenes.json")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = "openai/gpt-oss-120b"

MIN_VISUAL = 4.0
TARGET_VISUAL = 7.0
MAX_VISUAL = 9.0

HOOK_DURATION = 10.0
SECTION_CARD_DURATION = 2.2
POINT_DURATION = 7.0
OUTRO_DURATION = 8.0

TARGET_VARIATIONS = [
    5.2,
    6.4,
    7.1,
    4.8,
    6.0,
    7.6,
    5.5,
    6.8,
    4.5,
    7.3,
]

EMPHASIS_DURATION = 2.2
MIN_EMPHASIS_GAP = 4.0

SECTION_QUERY_COUNT = 5
CONCLUSION_QUERY_COUNT = 10


def load_voice():
    if not os.path.exists(VOICE_FILE):
        raise FileNotFoundError(VOICE_FILE)

    with open(VOICE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        segments = data
    elif isinstance(data, dict):
        if isinstance(data.get("segments"), list):
            segments = data["segments"]
        elif isinstance(data.get("voice_segments"), list):
            segments = data["voice_segments"]
        elif isinstance(data.get("data"), list):
            segments = data["data"]
        else:
            raise ValueError("Could not find voice segments")
    else:
        raise ValueError("Invalid voice_segments.json")

    return normalize_voice_segments(segments)


def extract_text(item):
    for key in [
        "text",
        "content",
        "sentence",
        "transcript",
        "words"
    ]:
        value = item.get(key)

        if isinstance(value, str):
            return value

        if isinstance(value, list):
            parts = []

            for x in value:
                if isinstance(x, str):
                    parts.append(x)
                elif isinstance(x, dict):
                    for k in ["word", "text", "content"]:
                        if k in x:
                            parts.append(str(x[k]))
                            break

            return " ".join(parts)

    return ""


def normalize_voice_segments(segments):
    result = []

    for i, item in enumerate(segments):
        if not isinstance(item, dict):
            continue

        start = (
            item.get("start")
            if item.get("start") is not None
            else item.get("start_time")
        )

        end = (
            item.get("end")
            if item.get("end") is not None
            else item.get("end_time")
        )

        if start is None or end is None:
            continue

        try:
            start = float(start)
            end = float(end)
        except Exception:
            continue

        text = extract_text(item).strip()

        if end <= start:
            continue

        result.append({
            "index": i,
            "start": start,
            "end": end,
            "text": text
        })

    result.sort(key=lambda x: x["start"])

    return result


def get_duration(voice):
    if not voice:
        return 0.0

    return max(float(x["end"]) for x in voice)


def read_content():
    if not os.path.exists(CONTENT_FILE):
        raise FileNotFoundError(CONTENT_FILE)

    with open(
        CONTENT_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        return f.read()




MARKER_PATTERN = re.compile(
    r"^\s*//\s*(INTRO|OUTRO|([1-5])\.\s*(.+?))\s*$",
    re.IGNORECASE
)


def make_anchor(text, word_count=14):
    """Build a short narration anchor from the beginning of a chapter."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        raise ValueError("Cannot create a narration anchor from an empty chapter.")
    words = text.split()
    return " ".join(words[:min(word_count, len(words))])


def parse_chapters(content):
    """Parse the exact INTRO, five numbered sections, and OUTRO markers."""
    lines = content.splitlines()
    markers = []

    for line_index, line in enumerate(lines):
        match = MARKER_PATTERN.match(line)
        if not match:
            continue

        label = match.group(1).strip().upper()
        if label == "INTRO":
            marker_type, number, title = "intro", None, "Introduction"
        elif label == "OUTRO":
            marker_type, number, title = "outro", None, "Conclusion"
        else:
            marker_type = "section"
            number = int(match.group(2))
            title = match.group(3).strip()
            if not title:
                raise ValueError(
                    f"Chapter marker on line {line_index + 1} has no title."
                )

        markers.append({
            "line_index": line_index,
            "type": marker_type,
            "number": number,
            "title": title,
            "original": line.strip(),
        })

    expected = [
        ("intro", None),
        ("section", 1),
        ("section", 2),
        ("section", 3),
        ("section", 4),
        ("section", 5),
        ("outro", None),
    ]
    actual = [(x["type"], x["number"]) for x in markers]
    if actual != expected:
        found = [x["original"] for x in markers]
        raise ValueError(
            "content.txt must contain exactly these seven markers in order:\n"
            "// INTRO\n// 1. Title\n// 2. Title\n// 3. Title\n"
            "// 4. Title\n// 5. Title\n// OUTRO\n\n"
            f"Markers found: {found}"
        )

    chapters = []
    for i, marker in enumerate(markers):
        body_start = marker["line_index"] + 1
        body_end = markers[i + 1]["line_index"] if i + 1 < len(markers) else len(lines)
        body = "\n".join(lines[body_start:body_end]).strip()
        if not body:
            raise ValueError(f"Chapter {marker['original']!r} has no narration.")
        chapters.append({
            "type": marker["type"],
            "number": marker["number"],
            "title": marker["title"],
            "body": body,
            "anchor": make_anchor(body),
        })

    sections = [x for x in chapters if x["type"] == "section"]
    analysis_parts = [f"INTRODUCTION:\n{chapters[0]['body']}"]
    for section in sections:
        analysis_parts.append(
            f"OPPORTUNITY {section['number']}: {section['title']}\n{section['body']}"
        )
    analysis_parts.append(f"CONCLUSION:\n{chapters[-1]['body']}")
    return {
        "intro": chapters[0],
        "sections": sections,
        "outro": chapters[-1],
        "analysis_text": "\n\n".join(analysis_parts),
    }


def load_chapter_times():
    """Read exact chapter starts emitted by voice.py, if available."""
    with open(VOICE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("chapters"), list):
        return None
    chapters = data["chapters"]
    if len(chapters) != 7:
        print(
            f"WARNING: voice_segments.json has {len(chapters)} chapter records; "
            "using narration-anchor matching instead."
        )
        return None
    try:
        starts = [float(chapter["start"]) for chapter in chapters]
    except (KeyError, TypeError, ValueError):
        print("WARNING: Chapter timing metadata is incomplete; using anchor matching.")
        return None
    if any(x < 0 for x in starts) or starts != sorted(starts) or len(set(starts)) != 7:
        print("WARNING: Chapter timing metadata is invalid; using anchor matching.")
        return None
    return {
        "intro": starts[0],
        "sections": starts[1:6],
        "outro": starts[6],
    }


def apply_chapter_markers(analysis, chapter_data):
    """Preserve model-generated visuals while forcing exact script titles/anchors."""
    model_sections = analysis.get("sections", [])
    if not isinstance(model_sections, list):
        model_sections = []
    fixed_sections = []
    for i, chapter in enumerate(chapter_data["sections"]):
        item = model_sections[i] if i < len(model_sections) and isinstance(model_sections[i], dict) else {}
        emphasis = item.get("emphasis", [])
        beats = item.get("visual_beats", [])
        fixed_sections.append({
            **item,
            "title": chapter["title"],
            "anchor": chapter["anchor"],
            "emphasis": emphasis if isinstance(emphasis, list) else [],
            "visual_beats": beats if isinstance(beats, list) else [],
        })
    analysis["sections"] = fixed_sections
    analysis["conclusion_anchor"] = chapter_data["outro"]["anchor"]
    return analysis


def groq_chat(system, user):
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY environment variable is missing"
        )

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODEL,
        "temperature": 0.1,
        # Ask Groq to enforce JSON syntax instead of relying on prompt-only formatting.
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": system
            },
            {
                "role": "user",
                "content": user
            }
        ]
    }

    # Groq TPM limits can reject the follow-up analysis if it is sent
    # immediately after the first large request. Respect the server's
    # suggested wait time and retry a few times instead of failing instantly.
    for attempt in range(4):
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=120
            )
        except requests.RequestException as exc:
            if attempt >= 3:
                raise RuntimeError(f"Could not connect to Groq: {exc}") from exc
            wait_seconds = 2 ** attempt
            print(f"Groq connection error; retrying in {wait_seconds}s...")
            time.sleep(wait_seconds)
            continue

        if response.status_code == 200:
            data = response.json()
            return data["choices"][0]["message"]["content"]

        if response.status_code == 429 and attempt < 3:
            body = response.text[:2000]
            match = re.search(r"try again in ([0-9.]+)s", body, re.IGNORECASE)
            wait_seconds = float(match.group(1)) + 1.0 if match else min(8 * (attempt + 1), 30)
            wait_seconds = max(2.0, min(wait_seconds, 65.0))
            print(
                f"Groq rate limit reached (429). Waiting "
                f"{wait_seconds:.1f}s before retry "
                f"{attempt + 1}/3..."
            )
            time.sleep(wait_seconds)
            continue

        raise RuntimeError(
            f"Groq error {response.status_code}: "
            f"{response.text[:2000]}"
        )

    raise RuntimeError("Groq request failed after retries")


def extract_json(text):
    """Extract a JSON object from a model response with useful diagnostics."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Groq returned an empty response instead of JSON")

    text = text.strip().lstrip("\ufeff")

    # Remove Markdown fences if a model emits them despite JSON mode.
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()

    start = text.find("{")
    if start == -1:
        raise ValueError(
            "No JSON object found in Groq response. Response preview:\n"
            + text[:1200]
        )

    # Decode from each opening brace in case the response has a short preamble.
    decoder = json.JSONDecoder()
    last_error = None
    for candidate_start in [m.start() for m in re.finditer(r"\{", text[start:])]:
        candidate_start += start
        try:
            value, _ = decoder.raw_decode(text[candidate_start:])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError as exc:
            last_error = exc

    if last_error is not None:
        line = last_error.lineno
        col = last_error.colno
        lines = text.splitlines()
        context = "\n".join(
            f"{i + 1}: {lines[i]}"
            for i in range(max(0, line - 3), min(len(lines), line + 2))
        )
        raise ValueError(
            "Groq response was not valid JSON: "
            f"{last_error.msg} at line {line}, column {col}.\n"
            f"Nearby response text:\n{context}\n"
            f"Response length: {len(text)} characters."
        ) from last_error

    raise ValueError("Groq response did not contain a valid JSON object")


def _fallback_section_analysis(content, partial_sections=None):
    """Create five safe section records locally if model analysis fails."""
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    if not text:
        raise ValueError("Narration content is empty; cannot build fallback sections.")

    raw_sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    sentences = [x.strip() for x in raw_sentences if len(x.strip()) >= 8]

    # Guarantee at least five usable regions, even for short/test inputs.
    # The prior fallback could loop forever when fewer than five regions existed.
    if len(sentences) < 5:
        words = text.split()
        if len(words) >= 5:
            chunk_size = max(1, math.ceil(len(words) / 5))
            sentences = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
        else:
            sentences = [text]
        while len(sentences) < 5:
            longest_index = max(range(len(sentences)), key=lambda i: len(sentences[i].split()))
            words_in_chunk = sentences.pop(longest_index).split()
            if len(words_in_chunk) < 2:
                sentences.insert(longest_index, " ".join(words_in_chunk))
                sentences.extend([text] * (5 - len(sentences)))
                break
            midpoint = max(1, len(words_in_chunk) // 2)
            sentences.insert(longest_index, " ".join(words_in_chunk[:midpoint]))
            sentences.insert(longest_index + 1, " ".join(words_in_chunk[midpoint:]))
        sentences = [x.strip() or text for x in sentences[:5]]

    heading_pattern = re.compile(
        r"^(?:(?:opportunity|method|way|idea|number)\s*)?(?:#?\s*[1-5]\s*[:.)\-–—]|(?:first|second|third|fourth|fifth)\b)",
        re.IGNORECASE,
    )
    starts = [i for i, sentence in enumerate(sentences) if heading_pattern.search(sentence)]

    if len(starts) >= 5:
        chosen = starts[:5]
    else:
        n = len(sentences)
        chosen = [min(n - 1, int(i * n / 5)) for i in range(5)]

    supplied = [x for x in partial_sections if isinstance(x, dict)] if isinstance(partial_sections, list) else []
    sections = []
    for i in range(5):
        source = sentences[chosen[i]]
        model_section = supplied[i] if i < len(supplied) else {}
        title = str(model_section.get("title") or "").strip()
        anchor = str(model_section.get("anchor") or "").strip()
        if not title:
            words = re.findall(r"[A-Za-z0-9$%'-]+", source)
            title = " ".join(words[:6]).strip(" .,:;-") or f"Opportunity {i + 1}"
            title = title[:72]
        if not anchor:
            anchor = " ".join(source.split()[:min(12, len(source.split()))]).strip()
        emphasis = model_section.get("emphasis", [])
        beats = model_section.get("visual_beats", [])
        if not isinstance(emphasis, list):
            emphasis = []
        if not isinstance(beats, list):
            beats = []
        if not beats:
            beats = [
                f"Close-up of hands carrying out a task related to {title.lower()}",
                f"Realistic workplace or small-business environment for {title.lower()}",
                f"Person reviewing a finished product or result related to {title.lower()}",
            ]
        sections.append({
            "title": title,
            "anchor": anchor,
            "emphasis": emphasis[:2],
            "visual_beats": [str(x) for x in beats[:3]],
        })

    conclusion_source = sentences[-1] if sentences else text
    conclusion_anchor = " ".join(conclusion_source.split()[:12]).strip()
    return {
        "sections": sections,
        "conclusion_anchor": conclusion_anchor,
        "conclusion_beats": [
            "Person reflecting on a plan at a desk",
            "Close-up of notes being organized into next steps",
            "Person beginning focused work in a bright workspace",
        ],
        "conclusion_emphasis": [],
    }


def analyze_sections(content):
    system = """
You are a professional YouTube documentary editor specializing in modern,
high-retention faceless business videos. Analyze the supplied narration and
return ONLY one valid JSON object. The narration has exactly five money-making
opportunities followed by a conclusion.

Return exactly five objects in sections. For each, provide title, an exact
consecutive narration phrase as anchor, up to two emphasis objects with text
and exact anchor, and exactly three distinct realistic stock-footage visual_beats.
Also provide conclusion_anchor, conclusion_beats, and conclusion_emphasis.
Never invent narration wording, figures, or timestamps. Keep the JSON compact.
"""
    user = f"NARRATION:\n\n{content}\n\nReturn compact JSON with exactly five sections."
    partial_sections = []
    try:
        raw = groq_chat(system=system, user=user)
        data = extract_json(raw)
        sections = data.get("sections", [])
        if isinstance(sections, list):
            partial_sections = [x for x in sections if isinstance(x, dict)]
        if isinstance(sections, list) and len(sections) == 5 and all(isinstance(x, dict) for x in sections):
            return data
        print(f"Groq returned {len(sections) if isinstance(sections, list) else 'invalid'} sections; attempting one compact repair request...")
        retry_user = (
            user + "\n\nThe previous response was incomplete. Return a compact JSON object only, "
            "with exactly five section objects. Use short anchors and no more than one emphasis item per section."
        )
        raw_retry = groq_chat(system=system, user=retry_user)
        retry_data = extract_json(raw_retry)
        retry_sections = retry_data.get("sections", [])
        if isinstance(retry_sections, list):
            retry_partial = [x for x in retry_sections if isinstance(x, dict)]
            if len(retry_partial) > len(partial_sections):
                partial_sections = retry_partial
        if isinstance(retry_sections, list) and len(retry_sections) == 5 and all(isinstance(x, dict) for x in retry_sections):
            return retry_data
        print("Groq still returned incomplete section JSON; using local fallback for missing/invalid analysis.")
        return _fallback_section_analysis(content, partial_sections)
    except Exception as exc:
        if isinstance(exc, RuntimeError) and "GROQ_API_KEY" in str(exc):
            raise
        print(f"Section analysis unavailable ({type(exc).__name__}: {exc}); using local fallback instead of aborting.")
        return _fallback_section_analysis(content, partial_sections)


def normalize_text(text):
    text = str(text or "").lower()

    text = text.replace("’", "'")
    text = text.replace("–", "-")
    text = text.replace("—", "-")

    text = re.sub(
        r"[^a-z0-9$%'.?!,\-\s]+",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def find_anchor_exact(
    voice,
    anchor,
    min_start=0.0
):
    target = normalize_text(anchor)

    if not target:
        return None

    for seg in voice:
        if seg["start"] < min_start:
            continue

        text = normalize_text(
            seg["text"]
        )

        if target in text:
            return seg["start"]

    combined = ""

    for seg in voice:
        if seg["start"] < min_start:
            continue

        combined += " " + normalize_text(
            seg["text"]
        )

        if target in combined:
            words = target.split()

            if words:
                approximate = max(
                    min_start,
                    seg["start"] - max(
                        0.0,
                        len(words) * 0.35
                    )
                )
                return approximate

        if len(combined) > len(target) * 4:
            combined = combined[-len(target) * 4:]

    return None


def find_anchor_fuzzy(
    voice,
    anchor,
    min_start=0.0
):
    target = normalize_text(anchor)

    if not target:
        return None

    best_score = 0.0
    best_start = None

    for i in range(len(voice)):
        if voice[i]["start"] < min_start:
            continue

        window = ""

        for j in range(
            i,
            min(
                len(voice),
                i + 10
            )
        ):
            window += " " + normalize_text(
                voice[j]["text"]
            )

            score = SequenceMatcher(
                None,
                target,
                window.strip()
            ).ratio()

            if score > best_score:
                best_score = score
                best_start = voice[i]["start"]

    if best_score >= 0.72:
        return best_start

    return None


def find_anchor_token_overlap(
    voice,
    anchor,
    min_start=0.0
):
    """Match an anchor when ASR changes a few words but preserves its key terms."""
    target_words = normalize_text(anchor).split()
    if not target_words:
        return None

    # Function words are weak evidence; prioritize distinctive anchor terms.
    stop_words = {
        "a", "an", "and", "are", "as", "at", "be", "been", "being",
        "but", "by", "for", "from", "had", "has", "have", "he", "her",
        "his", "how", "i", "in", "into", "is", "it", "its", "of",
        "on", "or", "our", "she", "that", "the", "their", "them",
        "they", "this", "to", "was", "we", "were", "what", "when",
        "which", "who", "with", "you", "your"
    }
    target_key = [w for w in target_words if w not in stop_words]
    if not target_key:
        target_key = target_words

    best_score = 0.0
    best_start = None
    best_matched = 0

    for i, first in enumerate(voice):
        if first["start"] < min_start:
            continue

        window_words = []
        for j in range(i, min(len(voice), i + 5)):
            window_words.extend(normalize_text(voice[j]["text"]).split())
            if not window_words:
                continue

            candidate_key = [w for w in window_words if w not in stop_words]
            if not candidate_key:
                candidate_key = window_words

            matched = 0
            used = set()
            for target_word in target_key:
                match_idx = None
                for k, candidate_word in enumerate(candidate_key):
                    if k in used:
                        continue
                    if target_word == candidate_word or SequenceMatcher(
                        None, target_word, candidate_word
                    ).ratio() >= 0.86:
                        match_idx = k
                        break
                if match_idx is not None:
                    used.add(match_idx)
                    matched += 1

            recall = matched / max(1, len(target_key))
            precision = matched / max(1, len(candidate_key))
            score = (2 * recall * precision / (recall + precision)) if (recall + precision) else 0.0

            # Require several distinctive words so a generic phrase cannot
            # accidentally become a section boundary.
            if matched >= min(3, len(target_key)) and score > best_score:
                best_score = score
                best_start = first["start"]
                best_matched = matched

    if best_start is not None and best_score >= 0.40:
        print(
            f"  Token-overlap anchor matched ({best_matched}/{len(target_key)} key words, "
            f"score {best_score:.2f}): {anchor}"
        )
        return best_start

    return None


def find_anchor(
    voice,
    anchor,
    min_start=0.0
):
    result = find_anchor_exact(
        voice,
        anchor,
        min_start
    )

    if result is not None:
        return result

    result = find_anchor_fuzzy(
        voice,
        anchor,
        min_start
    )

    if result is not None:
        print(
            f"  Fuzzy anchor matched: {anchor}"
        )
        return result

    return find_anchor_token_overlap(
        voice,
        anchor,
        min_start
    )


def detect_boundaries(
    voice,
    analysis,
    chapter_times=None
):
    sections = analysis["sections"]

    boundaries = []
    current_min = 0.0

    for i, section in enumerate(sections):
        title = str(
            section.get("title", "")
        ).strip()

        anchor = str(
            section.get("anchor", "")
        ).strip()

        # Prefer exact chapter timestamps written by voice.py. If unavailable,
        # fall back to transcript-anchor matching.
        if chapter_times and i < len(chapter_times.get("sections", [])):
            position = float(chapter_times["sections"][i])
        else:
            anchor_min = max(current_min, HOOK_DURATION) if i == 0 else current_min
            position = find_anchor(voice, anchor, anchor_min)

        # Defensive guard: some transcript/anchor combinations can still
        # resolve to an earlier segment (for example, stale or malformed
        # segment metadata). Never let the first section begin underneath
        # the hook, even if the anchor matcher returns an out-of-range time.
        if position is not None and i == 0 and not chapter_times:
            position = max(float(position), float(HOOK_DURATION))

        if position is None:
            raise ValueError(
                f"Could not locate section {i + 1} anchor:\n"
                f"{anchor}"
            )

        print(
            f"{i + 1}. {title} -> {position:.2f}s"
        )

        boundaries.append({
            "index": i + 1,
            "title": title,
            "start": position,
            "emphasis": section.get(
                "emphasis",
                []
            ),
            "visual_beats": section.get(
                "visual_beats",
                []
            )
        })

        current_min = position + 5.0

    conclusion_anchor = str(
        analysis.get("conclusion_anchor", "") or ""
    ).strip()

    if chapter_times and chapter_times.get("outro") is not None:
        conclusion_start = float(chapter_times["outro"])
    else:
        conclusion_start = find_anchor(
            voice,
            conclusion_anchor,
            current_min
        ) if conclusion_anchor else None

    if conclusion_start is None:
        # A model-generated conclusion anchor can be missing or differ from
        # the spoken transcript. Do not abort the entire timeline for that.
        # Fall back near the start of the final ~23% of the narration, while
        # keeping the conclusion safely after the fifth opportunity.
        duration = get_duration(voice)
        estimated_start = max(
            current_min,
            duration * 0.77
        )
        estimated_start = min(
            estimated_start,
            max(current_min, duration - OUTRO_DURATION - 1.0)
        )

        if estimated_start >= duration - 1.0:
            raise ValueError(
                "Could not estimate a valid conclusion start: "
                f"last section begins at {current_min - 5.0:.2f}s, "
                f"voice duration is {duration:.2f}s."
            )

        conclusion_start = estimated_start
        print(
            "  WARNING: Could not match the AI conclusion anchor "
            f"{conclusion_anchor!r}. Using estimated conclusion start "
            f"at {conclusion_start:.2f}s (77% of narration duration)."
        )

    conclusion_beats = analysis.get(
        "conclusion_beats",
        []
    )
    conclusion_emphasis = analysis.get(
        "conclusion_emphasis",
        []
    )
    if not isinstance(conclusion_emphasis, list):
        conclusion_emphasis = []

    return boundaries, conclusion_start, conclusion_beats, conclusion_emphasis


def clean_title(title):
    title = str(title or "").strip()

    title = re.sub(
        r"^[0-9]+\s*[-.)]\s*",
        "",
        title
    )

    return title


def slug_title(title):
    title = clean_title(title).lower()

    title = re.sub(
        r"[^a-z0-9\s-]",
        "",
        title
    )

    title = re.sub(
        r"\s+",
        "-",
        title
    )

    return title.strip("-")


def section_queries(title):
    t = clean_title(title)
    low = t.lower()

    if "podcast" in low:
        return [
            "podcaster recording podcast studio",
            "person planning podcast episode",
            "microphone laptop podcast workspace",
            "content creator podcast editing",
            "podcast production computer",
            "podcast analytics audience growth",
            "podcast outline planning"
        ]

    if "print" in low or "on-demand" in low:
        return [
            "graphic designer creating artwork laptop",
            "digital art design computer",
            "printing product packaging ecommerce",
            "online store product design",
            "creative designer tablet",
            "shirt product mockup ecommerce",
            "online clothing store analytics"
        ]

    if "newsletter" in low:
        return [
            "professional reading business news laptop",
            "person writing newsletter computer",
            "business research laptop",
            "professional office computer research",
            "email newsletter laptop",
            "email marketing analytics",
            "newsletter subscriber growth"
        ]

    if "prompt" in low or "engineering" in low:
        return [
            "developer working with artificial intelligence",
            "person typing laptop office",
            "client meeting technology consultant",
            "software developer computer screen",
            "business technology consulting",
            "AI prompt interface computer",
            "business owner using AI automation"
        ]

    if "discord" in low or "bot" in low:
        return [
            "developer coding computer",
            "online community computer",
            "software developer working laptop",
            "online community discussion",
            "gaming developer computer",
            "Discord community management",
            "online membership analytics"
        ]

    return [
        "entrepreneur working laptop",
        "business technology startup",
        "modern office computer",
        "person working online business",
        "digital entrepreneur"
    ]


def hook_queries():
    return [
        "entrepreneur working laptop night",
        "person building online business computer",
        "technology startup laptop",
        "fast business technology montage",
        "creative entrepreneur workspace",
        "AI business opportunity computer",
        "online business owner working",
        "startup founder laptop",
        "digital business analytics",
        "AI technology workspace"
    ]


def conclusion_queries():
    """Return a broad, non-repetitive visual pool for the long conclusion."""
    return [
        "entrepreneur reviewing business plan at desk",
        "close up hands editing digital design on tablet",
        "small business owner checking sales dashboard",
        "developer testing software on multiple monitors",
        "creator editing video at home workstation",
        "online store owner packing customer orders",
        "professional researching market trends on laptop",
        "startup team brainstorming around whiteboard",
        "person comparing business analytics charts",
        "freelancer working in modern home office",
        "hands typing code in dark computer workspace",
        "designer refining product mockup on screen",
        "email newsletter analytics on laptop screen",
        "podcast microphone and editing workstation",
        "ecommerce product photography workspace",
        "business owner planning weekly tasks in notebook",
        "close up computer screen with software dashboard",
        "person reviewing customer feedback at laptop",
        "small team collaborating in modern office",
        "entrepreneur working on laptop in a cafe",
        "abstract digital network and artificial intelligence technology",
        "hands sketching a product idea in notebook",
        "person recording educational content at desk",
        "online community discussion on computer screen",
        "professional checking website performance analytics",
        "focused creator working late at desk",
        "business owner reviewing invoices and revenue",
        "minimal modern workspace with laptop and notebook",
        "person looking at sunrise through office window",
        "confident entrepreneur closing laptop after work",
        "close up hand writing a clear business goal on paper",
        "creator reviewing finished work on a large monitor",
        "entrepreneur taking a walk outside a modern office",
        "small business owner discussing an idea with a colleague",
        "close up hands organizing a simple project checklist",
        "person editing a digital product before publishing",
        "creator setting up a camera and microphone at home",
        "professional looking over customer reviews at a desk",
        "sunlight across a calm modern home office workspace",
        "entrepreneur looking out across a city from an office"
    ]


def outro_queries():
    return [
        "modern city skyline night",
        "city lights night",
        "technology city night",
        "modern office night",
        "business city skyline"
    ]


def beat_queries(beats):
    result = []

    if isinstance(beats, list):
        for beat in beats:
            beat = str(beat).strip()

            if beat and beat not in result:
                result.append(beat)

    return result


def build_query_pool(
    title,
    visual_beats=None
):
    """Build a long, topic-specific pool so long sections don't cycle quickly."""
    base = section_queries(title)
    beat_list = beat_queries(visual_beats)
    non_stock_terms = (
        "screenshot", "screen capture", "graph visual", "graph showing",
        "chart highlighting", "exact revenue", "dashboard screenshot",
        "screen showing", "interface displaying"
    )
    beat_list = [
        query for query in beat_list
        if not any(term in query.lower() for term in non_stock_terms)
    ]
    low = clean_title(title).lower()

    if "podcast" in low:
        expansions = [
            "close up podcast microphone in recording booth",
            "podcaster adjusting microphone and headphones",
            "audio waveform being edited on computer screen",
            "creator preparing notes before recording a podcast",
            "sound engineer mixing audio at studio desk",
            "podcast host speaking into studio microphone",
            "home podcast recording setup with acoustic panels",
            "content creator reviewing recorded audio with headphones",
            "camera moving across podcast desk and equipment",
            "producer organizing episode notes beside microphone",
            "podcast studio lights and recording equipment",
            "creator exporting audio project on desktop computer",
        ]
    elif "print" in low or "on-demand" in low or "design" in low:
        expansions = [
            "close up digital illustration being refined with stylus",
            "designer comparing color palettes for a shirt design",
            "plain t-shirt mockups arranged on a studio table",
            "print shop printing a design onto a t-shirt",
            "folded printed shirts prepared for shipping",
            "designer checking product mockups on a large monitor",
            "hands sketching a graphic design in a notebook",
            "ecommerce seller photographing a product mockup",
            "shipping label and packaged clothing order on desk",
            "designer reviewing customer feedback on product artwork",
            "close up ink and fabric texture on printed apparel",
            "creative workspace with tablet and design samples",
        ]
    elif "newsletter" in low:
        expansions = [
            "professional highlighting key points in industry research",
            "editor reviewing articles and notes at a desk",
            "close up hands typing a newsletter draft",
            "email campaign being prepared at a home office",
            "business professional reading a briefing on a tablet",
            "researcher comparing multiple industry reports",
            "writer organizing research notes and printed articles",
            "person reviewing email engagement on a laptop",
            "newsletter creator planning a weekly publishing calendar",
            "professional reading business news over morning coffee",
            "editor proofreading a short digital article",
            "close up notebook with organized research bullet points",
        ]
    elif "prompt" in low or "engineering" in low:
        expansions = [
            "consultant explaining an automation workflow to a client",
            "developer testing an AI assistant at a workstation",
            "business team reviewing a customer support process",
            "freelancer documenting reusable instructions on a laptop",
            "close up hands reviewing code in an editor",
            "consultant taking notes during a client discovery meeting",
            "customer support agent working with an AI tool",
            "developer comparing test results on two monitors",
            "small business owner discussing workflow improvements",
            "professional presenting a process diagram to colleagues",
            "freelancer organizing project deliverables at a desk",
            "team collaborating around a laptop in a modern office",
        ]
    elif "discord" in low or "bot" in low:
        expansions = [
            "online community moderator managing a discussion",
            "developer testing a chat bot in a development environment",
            "gaming community members collaborating online",
            "close up hands typing bot commands on a keyboard",
            "creator planning paid community benefits at a desk",
            "developer debugging a small automation script",
            "online community manager reviewing member feedback",
            "digital creator preparing downloadable resource files",
            "team discussing community engagement around a laptop",
            "person managing memberships and digital products",
            "developer monitoring a bot running on a computer",
            "headset and keyboard on a community manager's desk",
        ]
    else:
        expansions = [
            "close up hands planning a digital product on paper",
            "creator reviewing a project at a modern desk",
            "small business owner checking customer feedback",
            "freelancer organizing deliverables in a home office",
            "professional comparing options on a laptop",
            "creator preparing a product for online customers",
            "business owner writing a weekly action plan",
            "close up hands typing at a clean workstation",
            "entrepreneur reviewing work beside a notebook",
            "person organizing digital files on a computer",
            "small team discussing a new online service",
            "creator finishing a project and reviewing the result",
        ]

    result = []
    for query in beat_list + base + expansions:
        query = str(query).strip()
        if query and query.casefold() not in {x.casefold() for x in result}:
            result.append(query)
    return result


def get_candidates(
    voice,
    start,
    end
):
    candidates = [
        start,
        end
    ]

    for seg in voice:
        if start < seg["start"] < end:
            candidates.append(
                seg["start"]
            )

        if start < seg["end"] < end:
            candidates.append(
                seg["end"]
            )

    length = end - start

    if length > MAX_VISUAL:
        pieces = math.ceil(
            length / TARGET_VISUAL
        )

        for i in range(1, pieces):
            point = (
                start +
                length * i / pieces
            )

            if start < point < end:
                candidates.append(point)

    candidates = sorted(
        set(
            round(float(x), 3)
            for x in candidates
        )
    )

    return candidates


def choose_cut(
    current,
    end,
    candidates,
    variation_index
):
    remaining = end - current

    if remaining <= MAX_VISUAL:
        return end

    target = TARGET_VARIATIONS[
        variation_index %
        len(TARGET_VARIATIONS)
    ]

    desired = current + target

    valid = [
        x for x in candidates
        if current + MIN_VISUAL <= x <= end
    ]

    if not valid:
        return min(
            end,
            current + target
        )

    best = min(
        valid,
        key=lambda x: abs(x - desired)
    )

    if best - current < MIN_VISUAL:
        return min(
            end,
            current + MIN_VISUAL
        )

    return best


def motion_for_index(index):
    motions = [
        "slow_zoom_in",
        "slow_zoom_out",
        "pan_left",
        "pan_right",
        "static",
        "slow_zoom_in",
        "slow_zoom_out"
    ]

    return motions[
        index % len(motions)
    ]


def build_visual_chunks(
    voice,
    start,
    end,
    section,
    section_index,
    queries,
    query_offset=0
):
    """Build continuous stock-visual scenes within the configured 4–9s range.

    Candidate cuts still prefer narration boundaries, but are constrained so
    that no normal visual exceeds MAX_VISUAL and the final remainder is not
    stranded as a sub-MIN_VISUAL scene. Very short source intervals (<4s) are
    retained as-is because they cannot be split without moving section edges.
    """
    if end <= start:
        return []

    if not queries:
        raise ValueError("build_visual_chunks received an empty query list")

    candidates = get_candidates(voice, start, end)
    result = []
    current = float(start)
    variation_index = 0
    query_index = max(0, int(query_offset))
    end = float(end)
    epsilon = 0.005

    while current < end - 0.01:
        remaining = end - current

        # A short final remainder is avoided by constraining every earlier cut
        # to leave at least MIN_VISUAL seconds for the final chunk.
        if remaining <= MAX_VISUAL + epsilon:
            cut = end
        else:
            lower = current + MIN_VISUAL
            upper = min(current + MAX_VISUAL, end - MIN_VISUAL)
            valid = [x for x in candidates if lower - epsilon <= x <= upper + epsilon]

            target = TARGET_VARIATIONS[variation_index % len(TARGET_VARIATIONS)]
            desired = min(current + target, upper)
            if valid:
                cut = min(valid, key=lambda x: abs(x - desired))
            else:
                cut = desired

            # Round only after choosing a valid cut, and guard against drift.
            cut = min(end - MIN_VISUAL, current + MAX_VISUAL, max(current + MIN_VISUAL, cut))

        cut = round(float(cut), 3)
        if cut <= current + 0.001:
            raise ValueError(
                f"Could not make forward progress building visuals: "
                f"current={current:.3f}, end={end:.3f}"
            )

        chunk_duration = cut - current
        if chunk_duration < MIN_VISUAL - 0.05 and result:
            # This should only be possible due to a very short overall interval.
            # Merge it into the previous scene only if that remains <= MAX_VISUAL.
            combined = cut - float(result[-1]["start"])
            if combined <= MAX_VISUAL + 0.05:
                result[-1]["end"] = round(cut, 3)
                result[-1]["duration"] = round(combined, 3)
                current = cut
                continue

        query = queries[query_index % len(queries)]
        scene = {
            "type": "visual",
            "start": round(current, 3),
            "end": round(cut, 3),
            "duration": round(chunk_duration, 3),
            "section": section_index,
            "section_title": clean_title(section["title"]),
            "query": query,
            "treatment": "stock",
            "motion": motion_for_index(variation_index),
            "overlay": None
        }
        result.append(scene)
        current = cut
        variation_index += 1
        query_index += 1

    return result


def find_emphasis_time(
    voice,
    anchor,
    section_start,
    section_end
):
    position = find_anchor(
        voice,
        anchor,
        section_start
    )

    if position is None:
        return None

    if position >= section_end:
        return None

    return position


def add_emphasis(
    scenes,
    voice,
    section,
    section_start,
    section_end
):
    emphasis = section.get(
        "emphasis",
        []
    )

    if not isinstance(
        emphasis,
        list
    ):
        return

    used = []

    for item in emphasis:
        if not isinstance(
            item,
            dict
        ):
            continue

        text = str(
            item.get("text", "")
        ).strip()

        anchor = str(
            item.get("anchor", "")
        ).strip()

        if not text or not anchor:
            continue

        position = find_emphasis_time(
            voice,
            anchor,
            section_start,
            section_end
        )

        if position is None:
            continue

        if any(
            abs(position - x) < MIN_EMPHASIS_GAP
            for x in used
        ):
            continue

        used.append(position)

        best_scene = None

        for scene in scenes:
            if (
                scene["start"] <= position <
                scene["end"]
            ):
                best_scene = scene
                break

        if best_scene is None:
            continue

        relative = (
            position -
            best_scene["start"]
        )

        if relative < 0.8:
            overlay_start = (
                best_scene["start"] +
                0.8
            )
        else:
            overlay_start = position

        overlay_duration = min(
            EMPHASIS_DURATION,
            best_scene["end"] -
            overlay_start -
            0.15
        )

        # If the spoken phrase lands near a cut, shift the overlay slightly
        # earlier instead of silently dropping an important emphasis moment.
        if overlay_duration < 1.0:
            overlay_start = max(
                best_scene["start"] + 0.2,
                best_scene["end"] - 1.15
            )
            overlay_duration = min(
                EMPHASIS_DURATION,
                best_scene["end"] - overlay_start - 0.15
            )

        if overlay_duration < 0.8:
            continue

        best_scene["treatment"] = (
            "stock_with_emphasis"
        )

        if best_scene.get(
            "overlay"
        ) is None:
            best_scene["overlay"] = {
                "type": "emphasis",
                "text": text,
                "start": round(
                    overlay_start,
                    3
                ),
                "duration": round(
                    overlay_duration,
                    3
                ),
                "animation": "punch"
            }


def make_scene(
    scene_id,
    scene_type,
    start,
    end,
    **kwargs
):
    data = {
        "id": scene_id,
        "type": scene_type,
        "start": round(
            start,
            3
        ),
        "end": round(
            end,
            3
        ),
        "duration": round(
            end - start,
            3
        )
    }

    data.update(kwargs)

    return data


def build_timeline(
    voice,
    duration,
    boundaries,
    conclusion_start,
    conclusion_beats,
    conclusion_emphasis=None
):
    scenes = []
    scene_id = 1

    hook_end = min(
        HOOK_DURATION,
        duration
    )

    scenes.append(
        make_scene(
            scene_id,
            "hook",
            0.0,
            hook_end,
            query=hook_queries()[0],
            query_pool=hook_queries(),
            treatment="hook_montage",
            motion="fast_montage",
            overlay={
                "type": "hook_text",
                "text": "AI MONEY OPPORTUNITIES",
                "start": 1.5,
                "duration": 2.0,
                "animation": "punch"
            }
        )
    )

    scene_id += 1

    for i, section in enumerate(
        boundaries
    ):
        section_start = float(section["start"])

        # Final safety net at timeline construction: the hook owns [0, 10),
        # so the first section/card/point must not start before hook_end.
        # This prevents a point scene at 2.2s overlapping a 0-10s hook.
        if i == 0:
            section_start = max(section_start, hook_end)

        section_end = (
            boundaries[i + 1]["start"]
            if i + 1 < len(boundaries)
            else conclusion_start
        )

        if section_end <= section_start:
            continue

        title = clean_title(
            section["title"]
        )

        # The introduction is the gap between the hook and the FIRST section
        # only. Running this for every section creates overlapping intro scenes
        # across the entire video and corrupts the timeline.
        if i == 0 and section_start > hook_end:
            gap_scenes = build_visual_chunks(
                voice,
                hook_end,
                section_start,
                {"title": "Introduction", "visual_beats": []},
                0,
                hook_queries(),
                query_offset=1
            )

            for gap_scene in gap_scenes:
                gap_scene["id"] = scene_id
                gap_scene["section"] = "intro"
                gap_scene["section_title"] = "Introduction"
                scenes.append(gap_scene)
                scene_id += 1

        card_end = min(
            section_start +
            SECTION_CARD_DURATION,
            section_end
        )

        if section_start >= hook_end:
            scenes.append(
                make_scene(
                    scene_id,
                    "section_card",
                    section_start,
                    card_end,
                    section=i + 1,
                    title=title,
                    display_text=(
                        f"{i + 1:02d} — "
                        f"{title.upper()}"
                    ),
                    background="white",
                    text_color="black",
                    animation="roll_in",
                    transition="roll_out"
                )
            )

            scene_id += 1

        point_start = max(
            card_end,
            section_start
        )

        # Keep a normal stock-visual scene of at least MIN_VISUAL seconds
        # at the end of a section whenever enough time remains. Shorten the
        # point intro for compact sections instead of creating a 1–3s stock
        # shot that later fails timeline validation. If fewer than MIN_VISUAL
        # seconds remain after the card, let the point intro use the remainder.
        available_after_point_start = section_end - point_start
        if available_after_point_start > MIN_VISUAL:
            point_end = min(
                point_start + POINT_DURATION,
                section_end - MIN_VISUAL
            )
        else:
            point_end = section_end

        if point_end > point_start:
            queries = build_query_pool(
                title,
                section.get(
                    "visual_beats",
                    []
                )
            )

            scenes.append(
                make_scene(
                    scene_id,
                    "point",
                    point_start,
                    point_end,
                    section=i + 1,
                    title=title,
                    query=queries[0],
                    query_pool=queries,
                    treatment="point_intro",
                    motion="slow_zoom_in"
                )
            )

            scene_id += 1

        visual_start = point_end

        if visual_start < section_end:
            queries = build_query_pool(
                title,
                section.get(
                    "visual_beats",
                    []
                )
            )

            chunks = build_visual_chunks(
                voice,
                visual_start,
                section_end,
                section,
                i + 1,
                queries,
                query_offset=1
            )

            for chunk in chunks:
                chunk["id"] = scene_id
                scenes.append(chunk)
                scene_id += 1

            visual_scenes = [
                x for x in scenes
                if (
                    x["type"] == "visual"
                    and
                    x.get("section") == i + 1
                )
            ]

            add_emphasis(
                visual_scenes,
                voice,
                section,
                section_start,
                section_end
            )

    conclusion_end = max(
        conclusion_start,
        duration - OUTRO_DURATION
    )

    if conclusion_end > conclusion_start:
        conclusion_section = {
            "title": "Conclusion",
            "visual_beats": conclusion_beats,
            "emphasis": conclusion_emphasis or []
        }

        conclusion_queries_pool = []
        for query in beat_queries(conclusion_beats) + conclusion_queries():
            if query not in conclusion_queries_pool:
                conclusion_queries_pool.append(query)

        conclusion_chunks = build_visual_chunks(
            voice,
            conclusion_start,
            conclusion_end,
            conclusion_section,
            0,
            conclusion_queries_pool
        )

        for index, chunk in enumerate(
            conclusion_chunks
        ):
            chunk["id"] = scene_id
            chunk["section"] = "conclusion"
            chunk["section_title"] = "Conclusion"

            if index == 0:
                chunk["treatment"] = "conclusion"

            scenes.append(chunk)
            scene_id += 1

        conclusion_visuals = [
            x for x in scenes
            if x.get("section") == "conclusion"
            and x.get("type") == "visual"
        ]
        add_emphasis(
            conclusion_visuals,
            voice,
            conclusion_section,
            conclusion_start,
            conclusion_end
        )

    if duration > conclusion_end:
        outro_start = conclusion_end

        scenes.append(
            make_scene(
                scene_id,
                "outro",
                outro_start,
                duration,
                query=outro_queries()[0],
                query_pool=outro_queries(),
                treatment="outro",
                motion="slow_zoom_out",
                overlay={
                    "type": "outro_text",
                    "text": "PICK ONE. START BUILDING.",
                    "start": round(
                        outro_start + 1.5,
                        3
                    ),
                    "duration": min(
                        3.0,
                        max(
                            0.0,
                            duration -
                            outro_start -
                            1.0
                        )
                    ),
                    "animation": "fade"
                }
            )
        )

    return scenes


def repair_timeline(scenes, duration):
    """Validate and minimally normalize the sequential scene timeline.

    This intentionally does not delete scenes, deduplicate same-start scenes,
    or stretch scenes across large gaps. Those behaviors hide timeline-builder
    bugs and can destroy section cards or point-intro scenes.
    """
    if not scenes:
        raise ValueError("No scenes generated")

    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Invalid video duration: {duration}")

    ordered = sorted(
        scenes,
        key=lambda scene: (float(scene.get("start", 0.0)), float(scene.get("end", 0.0)))
    )

    tolerance = 0.035
    cursor = 0.0

    for index, scene in enumerate(ordered):
        try:
            start = float(scene["start"])
            end = float(scene["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Scene at index {index} has missing/invalid start or end: {scene!r}"
            ) from exc

        scene_label = (
            f"id={scene.get('id', '?')}, type={scene.get('type', '?')}, "
            f"start={start:.3f}, end={end:.3f}"
        )

        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError(f"Non-finite scene interval: {scene_label}")
        if start < -tolerance or end > duration + tolerance:
            raise ValueError(
                f"Scene outside audio bounds (duration={duration:.3f}s): {scene_label}"
            )
        if end <= start:
            raise ValueError(f"Invalid scene interval: {scene_label}")

        # Snap only harmless floating-point/rounding differences. A meaningful
        # gap or overlap is an upstream bug and must not be silently rewritten.
        if abs(start - cursor) <= tolerance:
            start = cursor
        elif start > cursor:
            raise ValueError(
                f"Timeline gap before {scene_label}: previous end={cursor:.3f}s, "
                f"gap={start - cursor:.3f}s"
            )
        else:
            raise ValueError(
                f"Timeline overlap before {scene_label}: previous end={cursor:.3f}s, "
                f"overlap={cursor - start:.3f}s"
            )

        end = min(end, duration)
        if end <= start:
            raise ValueError(f"Scene became invalid after rounding: {scene_label}")

        scene["start"] = round(start, 3)
        scene["end"] = round(end, 3)
        scene["duration"] = round(end - start, 3)
        cursor = end

    if abs(cursor - duration) <= tolerance:
        ordered[-1]["end"] = round(duration, 3)
        ordered[-1]["duration"] = round(
            duration - float(ordered[-1]["start"]), 3
        )
    else:
        raise ValueError(
            f"Timeline ends at {cursor:.3f}s, but audio ends at {duration:.3f}s "
            f"(difference={duration - cursor:.3f}s)"
        )

    scenes[:] = ordered
    for scene_id, scene in enumerate(scenes, start=1):
        scene["id"] = scene_id

def merge_short_visuals(scenes):
    """Absorb sub-MIN_VISUAL stock shots into an adjacent stock shot when safe.

    Very short conclusion/introduction intervals can occur when an anchor lands
    close to the outro or a section boundary. Preserve continuous timing without
    rendering an awkward 1–3 second stock shot, but never create a visual longer
    than MAX_VISUAL.
    """
    scenes.sort(key=lambda scene: (float(scene["start"]), float(scene["end"])))
    index = 0
    while index < len(scenes):
        scene = scenes[index]
        length = float(scene["end"]) - float(scene["start"])
        if scene.get("type") != "visual" or length >= MIN_VISUAL - 0.05:
            index += 1
            continue

        merged = False
        if index > 0:
            previous = scenes[index - 1]
            previous_length = float(previous["end"]) - float(previous["start"])
            combined = float(scene["end"]) - float(previous["start"])
            if (
                previous.get("type") == "visual"
                and abs(float(previous["end"]) - float(scene["start"])) <= 0.035
                and combined <= MAX_VISUAL + 0.05
            ):
                previous["end"] = round(float(scene["end"]), 3)
                previous["duration"] = round(combined, 3)
                scenes.pop(index)
                print(
                    f"Merged short visual ({length:.2f}s) into previous visual; "
                    f"new duration={combined:.2f}s"
                )
                merged = True

        if merged:
            continue

        if index + 1 < len(scenes):
            following = scenes[index + 1]
            combined = float(following["end"]) - float(scene["start"])
            if (
                following.get("type") == "visual"
                and abs(float(scene["end"]) - float(following["start"])) <= 0.035
                and combined <= MAX_VISUAL + 0.05
            ):
                following["start"] = round(float(scene["start"]), 3)
                following["duration"] = round(combined, 3)
                scenes.pop(index)
                print(
                    f"Merged short visual ({length:.2f}s) into following visual; "
                    f"new duration={combined:.2f}s"
                )
                continue

        # Don't silently weaken validation if no safe adjacent merge exists.
        raise ValueError(
            f"Short visual cannot be safely merged: id={scene.get('id', '?')}, "
            f"duration={length:.3f}s, start={scene['start']:.3f}, end={scene['end']:.3f}"
        )

    for scene_id, scene in enumerate(scenes, start=1):
        scene["id"] = scene_id


def repair_overlay_times(scenes):
    """Keep each overlay finite, positive, and fully inside its parent scene."""
    for scene in scenes:
        overlay = scene.get("overlay")
        if not overlay:
            continue

        scene_start = float(scene["start"])
        scene_end = float(scene["end"])
        try:
            start = float(overlay.get("start", scene_start))
            duration = float(overlay.get("duration", 2.0))
        except (TypeError, ValueError):
            scene["overlay"] = None
            continue

        if not math.isfinite(start) or not math.isfinite(duration) or duration <= 0:
            scene["overlay"] = None
            continue

        # Keep a small inset to avoid edge clipping in renderers.
        inset_start = min(scene_start + 0.2, scene_end)
        inset_end = max(inset_start, scene_end - 0.1)
        start = min(max(start, inset_start), inset_end)
        overlay_end = min(start + duration, inset_end)

        if overlay_end - start <= 0.05:
            scene["overlay"] = None
            continue

        overlay["start"] = round(start, 3)
        overlay["duration"] = round(overlay_end - start, 3)


def validate_timeline(
    scenes,
    duration
):
    if not scenes:
        raise ValueError(
            "No scenes"
        )

    previous_end = 0.0

    for scene in scenes:
        start = float(
            scene["start"]
        )

        end = float(
            scene["end"]
        )

        if abs(
            start -
            previous_end
        ) > 0.01:
            raise ValueError(
                f"Gap/overlap detected: "
                f"{previous_end:.2f} -> "
                f"{start:.2f}"
            )

        if end <= start:
            raise ValueError(
                f"Invalid scene duration: "
                f"{scene['id']} "
                f"(start={start:.3f}, end={end:.3f})"
            )

        scene_type = str(scene.get("type", ""))
        if scene_type == "visual":
            scene_duration = end - start
            # Ordinary visual scenes are required to respect the published
            # 4–9s policy. Hook, point-intro, card, and outro timing are separate.
            if scene_duration < MIN_VISUAL - 0.05 or scene_duration > MAX_VISUAL + 0.05:
                raise ValueError(
                    f"Visual duration outside {MIN_VISUAL:.1f}–{MAX_VISUAL:.1f}s: "
                    f"id={scene.get('id', '?')}, duration={scene_duration:.3f}s, "
                    f"start={start:.3f}, end={end:.3f}"
                )

        overlay = scene.get("overlay")
        if overlay:
            try:
                overlay_start = float(overlay["start"])
                overlay_duration = float(overlay["duration"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid overlay timing in scene id={scene.get('id', '?')}") from exc
            overlay_end = overlay_start + overlay_duration
            if (
                not math.isfinite(overlay_start)
                or not math.isfinite(overlay_duration)
                or overlay_duration <= 0
                or overlay_start < start - 0.01
                or overlay_end > end + 0.01
            ):
                raise ValueError(
                    f"Overlay escapes its parent scene: id={scene.get('id', '?')}, "
                    f"overlay={overlay_start:.3f}–{overlay_end:.3f}, "
                    f"scene={start:.3f}–{end:.3f}"
                )

        previous_end = end

    if abs(
        previous_end -
        duration
    ) > 0.01:
        raise ValueError(
            f"Timeline ends at "
            f"{previous_end:.3f}, "
            f"expected {duration:.3f}"
        )


def validate_section_cards(
    scenes,
    boundaries
):
    cards = [
        x for x in scenes
        if x["type"] == "section_card"
    ]

    if len(cards) != len(boundaries):
        raise ValueError(
            f"Expected {len(boundaries)} "
            f"section cards, got {len(cards)}"
        )

    for i, boundary in enumerate(
        boundaries
    ):
        card = cards[i]

        if abs(
            card["start"] -
            boundary["start"]
        ) > 0.5:
            print(
                f"Warning: card {i + 1} "
                f"starts at {card['start']:.2f}s "
                f"instead of "
                f"{boundary['start']:.2f}s"
            )


def summarize(scenes):
    counts = {}

    for scene in scenes:
        t = scene["type"]
        counts[t] = counts.get(
            t,
            0
        ) + 1

    print()
    print("=" * 60)
    print("V14 SCENE SUMMARY")
    print("=" * 60)

    print(
        f"Scenes: {len(scenes)}"
    )

    for key, value in counts.items():
        print(
            f"{key}: {value}"
        )

    print()

    for scene in scenes:
        if scene["type"] == "section_card":
            print(
                f"[CARD] "
                f"{scene['display_text']} "
                f"{scene['start']:.2f}s -> "
                f"{scene['end']:.2f}s"
            )

        elif scene["type"] == "visual":
            overlay = scene.get(
                "overlay"
            )

            if overlay:
                print(
                    f"[TEXT] "
                    f"{overlay['text']} "
                    f"@ {overlay['start']:.2f}s"
                )


def main():
    print("=" * 70)
    print(
        "AI FACELESS CHANNEL - "
        "SCENE DETECTOR V14.4 - MARKER DRIVEN"
    )
    print("=" * 70)

    voice = load_voice()
    content = read_content()
    chapter_data = parse_chapters(content)
    chapter_times = load_chapter_times()

    duration = get_duration(
        voice
    )

    print(
        f"Voice duration: "
        f"{duration:.2f}s"
    )

    print()
    print("Chapter markers from content.txt:")
    for section in chapter_data["sections"]:
        print(f"  {section['number']}. {section['title']}")
    print("  OUTRO -> Conclusion")

    print()
    print("Analyzing visual ideas and emphasis...")
    analysis = analyze_sections(chapter_data["analysis_text"])
    analysis = apply_chapter_markers(analysis, chapter_data)

    if chapter_times:
        print("Using exact chapter timestamps from voice_segments.json.")
    else:
        print("Chapter timestamps unavailable; matching narration anchors.")

    print()
    print(
        "Detected sections:"
    )

    (
        boundaries,
        conclusion_start,
        conclusion_beats,
        conclusion_emphasis
    ) = detect_boundaries(
        voice,
        analysis,
        chapter_times
    )

    print()
    print(
        f"Conclusion -> "
        f"{conclusion_start:.2f}s"
    )

    print()
    print(
        "Building marker-driven timeline..."
    )

    scenes = build_timeline(
        voice,
        duration,
        boundaries,
        conclusion_start,
        conclusion_beats,
        conclusion_emphasis
    )

    repair_timeline(
        scenes,
        duration
    )

    merge_short_visuals(
        scenes
    )

    repair_overlay_times(
        scenes
    )

    validate_timeline(
        scenes,
        duration
    )

    validate_section_cards(
        scenes,
        boundaries
    )

    summarize(
        scenes
    )

    output = {
        "version": 14,
        "generator_version": "14.4-marker-driven",
        "duration": round(
            duration,
            3
        ),
        "visual_style": {
            "section_cards": {
                "background": "white",
                "text_color": "black",
                "animation": "roll_in",
                "style": "minimal_editorial",
                "duration": SECTION_CARD_DURATION
            },
            "emphasis": {
                "style": "large_bold_text",
                "animation": "punch",
                "duration": EMPHASIS_DURATION
            },
            "hook": {
                "style": "fast_montage"
            },
            "point_intro": {
                "style": "dynamic_intro",
                "duration": POINT_DURATION
            },
            "stock_visuals": {
                "min_duration": MIN_VISUAL,
                "target_duration": TARGET_VISUAL,
                "max_duration": MAX_VISUAL
            },
            "outro": {
                "style": "minimal_editorial"
            }
        },
        "sections": [
            {
                "number": i + 1,
                "title": clean_title(
                    x["title"]
                ),
                "start": round(
                    x["start"],
                    3
                )
            }
            for i, x in enumerate(
                boundaries
            )
        ],
        "conclusion_start": round(
            conclusion_start,
            3
        ),
        "scenes": scenes
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False
        )

    print()
    print("=" * 70)
    print("DONE")
    print("=" * 70)

    print(
        f"Output: {OUTPUT_FILE}"
    )

    print(
        "Generator version: 14.4-marker-driven"
    )

    print(
        f"Duration: "
        f"{duration:.2f}s"
    )

    print(
        f"Scenes: "
        f"{len(scenes)}"
    )


if __name__ == "__main__":
    main()
