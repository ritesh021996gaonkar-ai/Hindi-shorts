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


def pick_model(exclude=()):
    """Ask Google which models this key can use; pick the newest stable Flash."""
    r = requests.get(f"{API}/models", headers=_headers(),
                     params={"pageSize": 200}, timeout=60)
    r.raise_for_status()
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and n not in exclude
             and not any(x in n for x in ("image", "tts", "audio", "live", "lite", "exp", "preview"))]
    pool = flash or [n for n in names if "flash" in n and n not in exclude] or \
        [n for n in names if n not in exclude]
    if not pool:
        raise RuntimeError("no Gemini model available for this API key")
    print(f"  available flash models: {', '.join(sorted(flash)[:8])}")
    return max(pool, key=lambda n: (_version(n), "latest" not in n, -len(n)))


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
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0,
                             "responseMimeType": "application/json"},
    }
    global _MODEL
    model = _MODEL or config.GEMINI_MODEL
    tried = []
    for attempt in range(6):
        try:
            r = requests.post(f"{API}/models/{model}:generateContent",
                              headers=_headers(), json=body, timeout=300)
        except requests.exceptions.RequestException as e:   # too slow / network
            print(f"  {model} timed out or failed ({type(e).__name__}), trying another model")
            tried.append(model)
            model = pick_model(exclude=tried)
            print(f"  switching to {model}")
            continue
        if r.status_code in (404, 400) and "model" in r.text.lower():   # retired model
            print(f"  model {model} not available: {r.text[:200]}")
            tried.append(model)
            model = pick_model(exclude=tried)
            print(f"  switching to {model}")
            continue
        if r.status_code == 429:          # free-tier rate limit -> wait and retry
            print("  rate limited, waiting 60s")
            time.sleep(60)
            continue
        if r.status_code >= 400:
            print(f"  Gemini error {r.status_code}: {r.text[:400]}")
        r.raise_for_status()
        try:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(re.sub(r"^```(json)?|```$", "", text.strip()))
            if 6 <= len(data["scenes"]) <= 16:
                _MODEL = model          # remember the working model for the next videos
                return data
        except (json.JSONDecodeError, KeyError, IndexError):
            pass
        print(f"  script attempt {attempt + 1} was malformed, retrying")
    raise RuntimeError("Gemini did not return a valid script")
