
import os
import re
import sys
import time
from pathlib import Path

from google import genai
from groq import Groq


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = BASE_DIR / "content.txt"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-2.5-flash",
]

GROQ_MODEL = "openai/gpt-oss-120b"

WORD_TARGET_MIN = 1500
WORD_TARGET_MAX = 2000
WORD_TARGET = 1750

OPPORTUNITY_COUNT = 5

MAX_RETRIES = 3
RETRY_DELAY = 5


def log(message):
    print(message, flush=True)


def fail(message):
    log(f"\nERROR: {message}")
    raise SystemExit(1)


def build_prompt(topic):
    return f"""
You are an experienced YouTube scriptwriter who specializes in
engaging, realistic, well-researched videos about making money online.

Write a complete faceless YouTube narration about:

{topic}

The video should reflect the reality of making money online in 2026.

==================================================
CORE OBJECTIVE
==================================================

Create a compelling, useful, realistic video about exactly five
distinct ways to make money related to the topic.

The script must feel like a well-produced YouTube business video,
not a school essay, a lecture, a PowerPoint presentation, or an
AI-generated listicle.

The viewer should feel that someone knowledgeable is explaining
real opportunities to them in a natural and engaging way.

==================================================
LENGTH
==================================================

Aim for {WORD_TARGET} spoken words.

The acceptable range is {WORD_TARGET_MIN} to {WORD_TARGET_MAX}
spoken words, excluding the chapter marker lines.

Do not inflate the script with repetition just to reach the target.

Do not make the script unnecessarily short.

Give each of the five opportunities enough room to explain how it
works, why someone might pursue it, what makes it difficult, and
what its realistic potential looks like.

==================================================
STRUCTURE
==================================================

Use this overall structure:

1. A compelling introduction.
2. Five distinct money-making opportunities.
3. A natural conclusion.

The introduction should establish the topic, create curiosity,
and give the viewer a reason to keep watching.

Do not spend too long introducing the video.

Move into the first opportunity naturally.

Each opportunity should feel like a new chapter, but the narration
must flow naturally from one chapter to the next.

The conclusion should bring the ideas together and leave the viewer
with a practical way to think about choosing an opportunity.

Do not repeat the entire video in the conclusion.

==================================================
CHAPTER MARKERS — VERY IMPORTANT
==================================================

Insert exactly seven standalone marker lines into the script:

// INTRO

// 1. SHORT DESCRIPTIVE TITLE

// 2. SHORT DESCRIPTIVE TITLE

// 3. SHORT DESCRIPTIVE TITLE

// 4. SHORT DESCRIPTIVE TITLE

// 5. SHORT DESCRIPTIVE TITLE

// OUTRO

Replace each numbered title with a concise title that accurately
describes the actual opportunity discussed in that chapter.

For example, if the first opportunity is AI-powered freelancing,
the marker should be:

// 1. AI-Powered Freelancing

If the second opportunity is AI-curated newsletters, use:

// 2. AI-Curated Newsletters

These are examples only. Choose opportunities and titles that fit
the actual topic.

PLACEMENT RULES:

- Put // INTRO at the very beginning of the script.
- Put each numbered marker immediately before the spoken introduction
  to that opportunity.
- Put // OUTRO immediately before the conclusion.
- Keep all markers on separate lines.
- Do not put a marker inside a spoken paragraph.
- Do not add any other lines beginning with //.

The marker indicates the exact beginning of a new chapter.

The first spoken words after a numbered marker must naturally
introduce the opportunity identified by that marker.

For example:

// 1. AI-Powered Freelancing

The first opportunity is AI-powered freelancing. Instead of spending
hours producing everything from scratch, you can use AI to help
deliver useful services faster...

// 2. AI-Curated Newsletters

The next opportunity is AI-curated newsletters. Rather than trying
to cover every topic, you can focus on a specific audience and help
them keep up with the information that matters to them...

Do not copy these examples verbatim unless they genuinely fit
the script.

Vary the transitions so the narration sounds human and natural.

You may use transitions such as:

- "The first opportunity is..."
- "The next opportunity is..."
- "Another approach worth considering is..."
- "A different opportunity comes from..."
- "The final opportunity is..."

Use appropriate transitions instead of mechanically repeating
the same phrase five times.

Do not say "number one", "number two", or read out the chapter
numbers merely because the markers are numbered.

The markers are metadata for the video-generation pipeline.
They are not spoken narration.

==================================================
NARRATION STYLE
==================================================

Write for someone listening, not reading.

Use natural, conversational English.

Use contractions where appropriate.

Vary sentence length. Mix short, punchy sentences with longer
explanations when the topic requires them.

Use natural transitions between ideas.

Make important points memorable without exaggerating them.

The narration should sound like a confident, knowledgeable person
explaining something interesting to a friend.

Avoid overly formal vocabulary, robotic transitions, and repetitive
sentence structures.

Do not start every paragraph with "Now", "So", "However", or
"Moreover".

Do not repeatedly announce what the video is going to discuss.

Avoid generic filler such as:

"Let's dive in."
"In today's fast-paced digital world."
"In this ever-changing landscape."
"Without further ado."
"At the end of the day."
"Now, let's move on to the next point."

Use these kinds of phrases only if they genuinely fit the context;
prefer more natural alternatives.

==================================================
INTRODUCTION
==================================================

The opening should quickly establish an interesting reason to watch.

Start with a compelling observation, contrast, problem, or surprising
but supportable insight.

Avoid generic openings such as:

"Have you ever wanted to make money online?"
"Making money online has become increasingly popular."
"Welcome to another video."

Do not promise that the viewer will become rich.

Do not make unrealistic claims about earning money quickly.

Get to the substance of the video without a long introduction.

==================================================
THE FIVE OPPORTUNITIES
==================================================

Choose exactly five meaningfully different opportunities that fit
the topic.

Avoid presenting essentially the same business model five times
under different names.

For each opportunity, naturally explain the following where relevant:

1. What the opportunity actually is.
2. What a person would do in practice.
3. Who might pay for it and why.
4. How the business or income model works.
5. What skills, tools, time, or resources are needed.
6. What makes the opportunity attractive.
7. Its limitations, competition, risks, or disadvantages.
8. What a realistic starting approach might look like.
9. What could make someone more successful at it.

These are writing guidelines, not headings.

Do not turn these into a repetitive checklist that appears in every
chapter. Integrate the relevant details into the narration naturally.

Use concrete examples to make abstract business ideas understandable.

Explain mechanisms rather than merely naming opportunities.

For example, if discussing a service business, explain what the
customer needs, what the provider delivers, and why the customer
would pay for it.

If discussing a product business, explain the value of the product,
how it reaches customers, and what affects its profitability.

If discussing an AI-related business, explain where AI actually helps
and where human judgment, quality control, or customer relationships
still matter.

Do not provide long, click-by-click tutorials for websites or tools.

The goal is to explain the opportunity, not to teach every button
someone must click.

==================================================
REALISM AND ACCURACY
==================================================

Be realistic about money, effort, and competition.

Do not imply that using AI automatically creates a profitable
business.

Do not invent statistics, studies, quotations, case studies,
customer stories, earnings, or market figures.

Do not present hypothetical examples as real people or real results.

Only include numerical claims when you have a reliable basis for them.
If a specific number cannot be supported, explain the concept
without inventing a statistic.

Distinguish revenue from profit where relevant.

Explain important costs, such as software, advertising, platform
fees, production expenses, or customer acquisition, when applicable.

Acknowledge that income is uncertain and that results depend on
execution, demand, competition, and other factors.

Do not make every opportunity sound equally easy or equally good.

Give each opportunity its own advantages and disadvantages.

Do not portray every business as a guaranteed passive-income stream.

Focus on practical, credible opportunities rather than hype.

==================================================
KEEP THE VIDEO ENGAGING
==================================================

Use different angles to explain different opportunities.

One chapter might focus on the advantage of a business model.
Another might explain how the model generates revenue.
Another might explore competition or an overlooked customer need.
Another might examine the practical difficulty of delivering the
service consistently.

Do not force every chapter into the same pattern.

Avoid repeatedly using phrases such as:

"The biggest advantage is..."
"The biggest disadvantage is..."
"Here's the catch..."
"The key takeaway is..."

Use them only when they fit naturally.

Avoid excessive rhetorical questions.

Do not repeat the same facts in multiple chapters.

Every paragraph should contribute a new idea, explanation, example,
comparison, or useful insight.

==================================================
CONCLUSION
==================================================

The conclusion should sound like the natural end of the discussion.

Do not introduce a sixth opportunity.

Do not repeat all five chapters one by one.

Give the viewer a useful way to evaluate the opportunities and decide
which might fit their own skills, resources, and interests.

End with a memorable, grounded final thought.

Do not add a long, generic motivational speech.

==================================================
OUTPUT FORMAT
==================================================

Return only the finished narration and the seven required chapter
marker lines.

No markdown formatting.
No additional headings.
No bullet points.
No numbered lists outside the required marker lines.
No citations or source list.
No visual directions.
No sound-effect directions.
No explanations outside the narration.

The only permitted non-spoken lines are:

// INTRO
// 1. SHORT DESCRIPTIVE TITLE
// 2. SHORT DESCRIPTIVE TITLE
// 3. SHORT DESCRIPTIVE TITLE
// 4. SHORT DESCRIPTIVE TITLE
// 5. SHORT DESCRIPTIVE TITLE
// OUTRO

Remember: the numbered marker lines are not spoken narration.
The spoken introduction following each marker must introduce the
matching opportunity naturally.

Return the complete script in its final form.
"""


def clean_script(script):
    script = script.replace("\ufeff", "")
    script = script.replace("\r\n", "\n").replace("\r", "\n")

    cleaned_lines = []

    for raw_line in script.splitlines():
        line = raw_line.strip()

        if not line:
            cleaned_lines.append("")
            continue

        # Preserve chapter markers exactly.
        if line.startswith("//"):
            cleaned_lines.append(line)
            continue

        # Remove common markdown formatting without removing narration.
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^\*\*(.*?)\*\*$", r"\1", line)
        line = re.sub(r"^\*(.*?)\*$", r"\1", line)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d+[\.)]\s+", "", line)

        # Remove common wrappers sometimes returned by AI models.
        if line.startswith("```"):
            continue

        cleaned_lines.append(line)

    script = "\n".join(cleaned_lines)
    script = re.sub(r"\n{3,}", "\n\n", script)

    return script.strip() + "\n"


def extract_markers(script):
    markers = []

    for line_number, line in enumerate(script.splitlines(), start=1):
        stripped = line.strip()

        if stripped.startswith("//"):
            markers.append((line_number, stripped))

    return markers


def validate_chapter_markers(script):
    markers = extract_markers(script)

    if len(markers) != 7:
        raise ValueError(
            f"Expected exactly 7 chapter markers, found {len(markers)}."
        )

    if markers[0][1].upper() != "// INTRO":
        raise ValueError(
            "The first marker must be // INTRO."
        )

    if markers[-1][1].upper() != "// OUTRO":
        raise ValueError(
            "The final marker must be // OUTRO."
        )

    titles = []

    for expected_number, (line_number, marker) in enumerate(
        markers[1:6],
        start=1
    ):
        match = re.fullmatch(
            rf"//\s*{expected_number}\.\s*(.+?)\s*",
            marker
        )

        if not match:
            raise ValueError(
                f"Invalid or out-of-order chapter marker on line "
                f"{line_number}: {marker!r}"
            )

        title = match.group(1).strip()

        if not title:
            raise ValueError(
                f"Chapter {expected_number} has an empty title."
            )

        titles.append(title)

    for line_number, line in enumerate(script.splitlines(), start=1):
        if line.strip().startswith("//"):
            allowed = (
                line.strip().upper() in {"// INTRO", "// OUTRO"}
                or any(
                    line.strip() == f"// {i}. {title}"
                    for i, title in enumerate(titles, start=1)
                )
            )

            if not allowed:
                raise ValueError(
                    f"Unexpected marker on line {line_number}: {line.strip()!r}"
                )

    positions = [
        line_number
        for line_number, _ in markers
    ]

    if positions != sorted(positions):
        raise ValueError("Chapter markers are not in the correct order.")

    return titles


def spoken_text(script):
    lines = []

    for line in script.splitlines():
        if line.strip().startswith("//"):
            continue

        lines.append(line)

    return "\n".join(lines).strip()


def count_words(text):
    return len(re.findall(r"\b[\w'-]+\b", text))


def generate_with_gemini(prompt):
    if not GEMINI_API_KEY:
        log("GEMINI_API_KEY is not set. Skipping Gemini.")
        return None

    client = genai.Client(api_key=GEMINI_API_KEY)

    for model in GEMINI_MODELS:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log(
                    f"\nTrying Gemini model {model} "
                    f"(attempt {attempt}/{MAX_RETRIES})..."
                )

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                )

                result = getattr(response, "text", None)

                if result and result.strip():
                    log(f"Gemini succeeded using {model}.")
                    return result.strip()

                log("Gemini returned an empty response.")

            except Exception as exc:
                log(
                    f"Gemini error with {model}: "
                    f"{type(exc).__name__}: {exc}"
                )

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    log("Gemini models failed. Trying Groq.")
    return None


def generate_with_groq(prompt):
    if not GROQ_API_KEY:
        log("GROQ_API_KEY is not set.")
        return None

    client = Groq(api_key=GROQ_API_KEY)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log(
                f"\nTrying Groq model {GROQ_MODEL} "
                f"(attempt {attempt}/{MAX_RETRIES})..."
            )

            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional YouTube scriptwriter. "
                            "Follow the user's formatting and chapter-marker "
                            "requirements exactly. Return only the script."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.75,
                max_completion_tokens=8192,
            )

            result = response.choices[0].message.content

            if result and result.strip():
                log("Groq generation succeeded.")
                return result.strip()

            log("Groq returned an empty response.")

        except Exception as exc:
            log(
                f"Groq error: {type(exc).__name__}: {exc}"
            )

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)

    return None


def generate_script(topic):
    prompt = build_prompt(topic)

    script = generate_with_gemini(prompt)

    if script:
        try:
            cleaned = clean_script(script)
            validate_chapter_markers(cleaned)
            return cleaned
        except ValueError as exc:
            log(f"Gemini output failed validation: {exc}")
            log("Trying Groq for a correctly formatted script.")

    script = generate_with_groq(prompt)

    if script:
        cleaned = clean_script(script)
        validate_chapter_markers(cleaned)
        return cleaned

    fail(
        "Both script-generation providers failed to produce a valid "
        "script. Check your API keys, model availability, quota, and "
        "internet connection."
    )


def save_script(script):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as file:
        file.write(script)

    log(f"\nScript saved to: {OUTPUT_FILE}")


def main():
    log("=" * 60)
    log("AI YOUTUBE SCRIPT GENERATOR")
    log("=" * 60)

    if not GEMINI_API_KEY and not GROQ_API_KEY:
        fail(
            "No API keys found. Set GEMINI_API_KEY and/or GROQ_API_KEY "
            "in your environment."
        )

    if len(sys.argv) > 1:
        topic = " ".join(sys.argv[1:]).strip()
    else:
        topic = input(
            "\nEnter the video topic "
            "(default: 5 ways to make money online): "
        ).strip()

    if not topic:
        topic = "5 ways to make money online"

    log(f"\nTopic: {topic}")
    log(f"Target length: {WORD_TARGET_MIN}-{WORD_TARGET_MAX} words")
    log("Required chapters: 5")
    log("Output: content.txt")

    script = generate_script(topic)

    titles = validate_chapter_markers(script)
    narration = spoken_text(script)
    word_count = count_words(narration)

    log("\n" + "=" * 60)
    log("SCRIPT VALIDATION")
    log("=" * 60)

    log(f"Spoken word count: {word_count}")
    log("\nChapter titles:")

    for index, title in enumerate(titles, start=1):
        log(f"  {index:02d}. {title}")

    if word_count < WORD_TARGET_MIN or word_count > WORD_TARGET_MAX:
        log(
            f"\nWARNING: The script has {word_count} spoken words. "
            f"The target range is {WORD_TARGET_MIN}-{WORD_TARGET_MAX}."
        )
        log("The script will still be saved.")

    save_script(script)

    log("\n" + "=" * 60)
    log("RESEARCH COMPLETE")
    log("=" * 60)
    log("Chapter markers are included in content.txt.")
    log("The voice pipeline must remove marker lines before TTS.")


if __name__ == "__main__":
    main()

