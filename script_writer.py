"""Writes an original Hindi script (with scene-by-scene visual prompts) using Gemini."""
import json
import re

import requests

import config

STYLE = """
You write ORIGINAL YouTube Shorts scripts in HINDI for the channel "{channel}".
Niche: {niche}.

Format of every short (fast, curious, 3D-animated explainer style):
- Line 1 is a HOOK that makes the viewer stop scrolling, usually a question or a
  shocking situation addressed to the viewer ("Agar aap..."/"Kya hoga agar...").
- Then explain step by step what happens, with a surprising twist near the end.
- End with a short punchline or open question (no "like and subscribe").
- Simple spoken Hindi in Devanagari script. Common English words (like "oxygen",
  "brain") may stay in English but written in Devanagari.
- Total narration: 135-160 words (about 55-60 seconds when spoken).
- 10 to 12 scenes. Each scene = 1 short sentence of narration (8-16 words).
- Facts must be accurate. No medical advice, no gore, nothing graphic or scary
  for children, no real people, no brands, no copyrighted characters.

For each scene also write "visual": an ENGLISH prompt for an AI video model.
Every visual prompt must start with:
"Stylized 3D animation, soft cinematic lighting, vertical 9:16, "
and describe ONE clear shot with simple motion. Use the SAME original main
character in every scene: "{character}". Never mention any existing show,
creator, film or character.

Avoid these topics, already used: {avoid}

Return ONLY JSON:
{{"topic_en": "...", "title": "Hindi title under 70 chars with 1 emoji",
  "description": "2-3 Hindi sentences", "tags": ["8-12 tags, Hindi and English"],
  "scenes": [{{"narration": "Hindi sentence", "visual": "English prompt"}}]}}
"""

# The channel's own mascot. Change it if you like, but keep it your own design.
CHARACTER = ("Chotu, a small round teal robot with one big glowing yellow eye, "
             "stubby arms and a tiny antenna, curious expression")


def write_script(avoid_topics):
    prompt = STYLE.format(
        channel=config.CHANNEL_NAME,
        niche=config.NICHE,
        character=CHARACTER,
        avoid="; ".join(avoid_topics[-150:]) or "none",
    )
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{config.GEMINI_MODEL}:generateContent")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0,
                             "responseMimeType": "application/json"},
    }
    for attempt in range(3):
        r = requests.post(url, params={"key": config.GEMINI_API_KEY},
                          json=body, timeout=120)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        try:
            data = json.loads(re.sub(r"^```(json)?|```$", "", text.strip()))
            if 6 <= len(data["scenes"]) <= 16:
                return data
        except (json.JSONDecodeError, KeyError):
            pass
        print(f"  script attempt {attempt + 1} was malformed, retrying")
    raise RuntimeError("Gemini did not return a valid script")
