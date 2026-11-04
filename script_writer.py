"""Writes an original Hindi script (with scene-by-scene visual prompts) using Gemini."""
import json
import re
import time

import requests

import config


_MODEL = ""
API = "https://generativelanguage.googleapis.com/v1beta"


def _headers():
    # header works for both old (AIza...) and new (AQ...) key formats
    return {"x-goog-api-key": config.GEMINI_API_KEY.strip()}


def _version(name):
    nums = re.findall(r"\d+(?:\.\d+)?", name)
    return float(nums[0]) if nums else 0.0


def candidate_models():
    """Ask Google which models this key can use; newest stable Flash first."""
    r = requests.get(f"{API}/models", headers=_headers(),
                     params={"pageSize": 200}, timeout=60)
    r.raise_for_status()
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    bad = ("image", "tts", "audio", "live", "lite", "exp", "preview", "omni")
    flash = [n for n in names if "flash" in n and not any(x in n for x in bad)]
    flash.sort(key=lambda n: (_version(n), "latest" not in n, -len(n)), reverse=True)
    others = [n for n in names if n not in flash and "flash" in n]
    print(f"  available models: {', '.join(flash[:8])}")
    return flash + others

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
- Total narration: 110-125 words MAXIMUM (must fit in 55 seconds when spoken).
- 9 to 11 scenes. Each scene = 1 short sentence of narration (8-13 words).
- Facts must be accurate. No medical advice, no gore, nothing graphic or scary
  for children, no real people, no brands, no copyrighted characters.

For each scene also write, in ENGLISH:
- "visual": an image prompt that shows EXACTLY what that scene's narration says
  (the same object, body part, place or event - literal, easy to understand).
  Start with "Stylized 3D cartoon animation render, vibrant colors, soft
  cinematic lighting, highly detailed, vertical composition, " then describe
  ONE clear shot: subject, action, setting, camera angle (close-up / wide /
  top-down / inside-the-body etc). Vary the camera angle from scene to scene.
  When a person is needed, use the SAME original mascot: "{character}".
- "motion": one sentence describing how things MOVE in the next 5 seconds
  (e.g. "the robot jumps back in surprise as the ground cracks, camera slowly
  pushes in"). Strong, clear, physical motion; one main action.
Never mention any existing show, creator, film, brand or real person.

Avoid these topics, already used: {avoid}

Return ONLY JSON:
{{"topic_en": "...", "title": "Hindi title under 70 chars with 1 emoji",
  "description": "2-3 Hindi sentences", "tags": ["8-12 tags, Hindi and English"],
  "scenes": [{{"narration": "Hindi sentence", "visual": "English image prompt",
               "motion": "English motion sentence"}}]}}
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
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0,
                             "responseMimeType": "application/json"},
    }
    global _MODEL
    queue = [_MODEL or config.GEMINI_MODEL]
    listed = False
    attempt = 0
    while queue and attempt < 14:
        model = queue[0]
        attempt += 1
        try:
            r = requests.post(f"{API}/models/{model}:generateContent",
                              headers=_headers(), json=body, timeout=300)
            code, text_body = r.status_code, r.text
        except requests.exceptions.RequestException as e:
            code, text_body = 0, type(e).__name__

        if code == 200:
            try:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                data = json.loads(re.sub(r"^```(json)?|```$", "", text.strip()))
                if 6 <= len(data["scenes"]) <= 16:
                    _MODEL = model          # remember the working model
                    print(f"  script written with {model}")
                    return data
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                pass
            print(f"  {model}: script was malformed, retrying")
            continue

        print(f"  {model}: error {code} {text_body[:160]}")
        retired = code in (400, 404) and "model" in text_body.lower()
        if code in (401, 403) and not retired:
            raise RuntimeError("Gemini key rejected - check the GEMINI_API_KEY secret")
        if not listed:                       # first problem -> learn all models
            listed = True
            queue += [m for m in candidate_models() if m not in queue]
        if retired or attempt % 2 == 0:      # retired, or failed twice -> next model
            queue.pop(0)
        wait = 0 if retired else min(15 * attempt, 90)   # busy -> wait, then retry
        if wait:
            print(f"  waiting {wait}s before retry")
            time.sleep(wait)
    raise RuntimeError("Gemini did not return a valid script")
