"""Long Hindi documentary videos (10-15 min, 16:9) with illustrated pictures
matched to every line of narration, YouTube chapters and a thumbnail.

Usage:
  python longform.py                      # make 1 video and upload/schedule it
  python longform.py --no-upload          # test: make the video only
  python longform.py --topic "हड़प्पा सभ्यता"   # choose the topic yourself
  python longform.py --mock               # offline test (fake script/voice/images)
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import random
import re
import traceback

import config
import media

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "output"
HISTORY = ROOT / "data" / "long_history.json"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

W, H, FPS = 1920, 1080, 30
NICHE = os.environ.get("LONG_NICHE", "").strip() or (
    "history documentaries: ancient civilizations, Indian history, empires, lost cities, "
    "great inventions and turning points of world history")
MINUTES = int(os.environ.get("LONG_MINUTES") or 12)
VOICE_RATE = os.environ.get("LONG_VOICE_RATE", "").strip() or "+0%"
SUBTITLES = (os.environ.get("LONG_SUBTITLES", "").strip() or "false").lower() == "true"
PUBLISH_TIME_IST = os.environ.get("LONG_PUBLISH_TIME_IST", "").strip() or "18:00"

# The channel's own art style (keep it the same in every picture).
ART = ("Detailed hand-drawn ink illustration, graphic-novel style, clean black linework, "
       "warm earthy watercolor colors, soft natural light, rich background detail, "
       "cinematic wide 16:9 composition, no text, no letters, no watermark. ")


# ---------------- script ----------------
OUTLINE = """You are the head writer of a Hindi YouTube history documentary channel.
Niche: {niche}.
Plan ONE original documentary of about {minutes} minutes.{topic_line}
Avoid these topics, already made: {avoid}

Rules: accurate, well-established facts only (no invented quotes, dates or numbers;
when historians disagree, say so). Respectful to all religions and communities.
No graphic violence. Storytelling, curious tone, simple spoken Hindi.

Return ONLY JSON:
{{"topic_en": "short English topic",
  "title": "Hindi YouTube title, curiosity-driven, under 70 characters",
  "thumbnail_text": "2 to 4 BIG Hindi words for the thumbnail",
  "thumbnail_scene": "English description of one dramatic, iconic scene for the thumbnail, leave the top third simple (sky) for text",
  "description": "3-4 Hindi sentences for the YouTube description",
  "tags": ["10-15 tags, Hindi and English"],
  "chapters": [{{"title": "Hindi chapter title", "summary": "English: what this chapter covers, key facts"}}]}}
Use 7 to 9 chapters. Chapter 1 is a HOOK: start from a surprising modern-day
connection or mystery, then go back in time. The last chapter ends with what we can
learn today and one open question.
"""

CHAPTER = """You are writing chapter {n} of {total} of a Hindi history documentary
titled "{title}". Whole outline: {outline}
This chapter: "{ch_title}" - {summary}
Previous chapter ended with: "{prev}"

Write about {words} Hindi words of narration, split into {scenes} scenes.
Each scene = 1 or 2 spoken sentences (15 to 30 words), Devanagari script, natural
storytelling Hindi (like a good narrator talking to a friend), smooth flow from
scene to scene. Accurate facts only.

For each scene also write "visual": an ENGLISH picture description that shows
EXACTLY what that narration is about (the place, people, object, event or map),
with era-correct clothes, buildings and tools. One clear shot; vary the angle
(wide landscape, close-up of hands/objects, aerial view, cutaway diagram, old map
on a table, people at work). Do NOT include any text or letters in the picture.
Do not depict real modern people.

Return ONLY JSON: {{"scenes": [{{"narration": "...", "visual": "..."}}]}}
"""


def write_long_script(avoid, topic=None):
    from script_writer import ask_json
    topic_line = f'\nThe topic MUST be: "{topic}".' if topic else ""
    outline = ask_json(OUTLINE.format(niche=NICHE, minutes=MINUTES, topic_line=topic_line,
                                      avoid="; ".join(avoid[-100:]) or "none"),
                       lambda d: 5 <= len(d["chapters"]) <= 12 and d["title"])
    print(f"  outline: {outline['title']} ({len(outline['chapters'])} chapters)")
    short_outline = " | ".join(f"{i + 1}. {c['title']}" for i, c in enumerate(outline["chapters"]))
    total_words = MINUTES * 130                   # Hindi narration ~130 words/minute
    per_ch = max(120, total_words // len(outline["chapters"]))
    prev = "(this is the start)"
    for n, ch in enumerate(outline["chapters"], 1):
        data = ask_json(CHAPTER.format(
            n=n, total=len(outline["chapters"]), title=outline["title"], outline=short_outline,
            ch_title=ch["title"], summary=ch.get("summary", ""), prev=prev,
            words=per_ch, scenes=max(6, per_ch // 22)),
            lambda d: len(d["scenes"]) >= 4 and all(s["narration"] and s["visual"] for s in d["scenes"]),
            temperature=0.9)
        ch["scenes"] = data["scenes"]
        prev = ch["scenes"][-1]["narration"]
        print(f"  chapter {n}: {len(ch['scenes'])} scenes")
    return outline


def mock_script():
    return {"topic_en": "mock", "title": "हड़प्पा: 5000 साल पुराना रहस्य",
            "thumbnail_text": "खोया हुआ शहर", "thumbnail_scene": "x",
            "description": "टेस्ट वीडियो।", "tags": ["test"],
            "chapters": [{"title": f"अध्याय {c}", "scenes": [
                {"narration": "सोचिए, पाँच हज़ार साल पहले यहाँ एक पूरा शहर बसता था।", "visual": "x"},
                {"narration": "सीधी सड़कें, पक्की ईंटों के घर और ढकी हुई नालियाँ।", "visual": "x"}]}
                for c in range(1, 4)]}


# ---------------- pictures ----------------
LAST_IMG = [None]


def picture(prompt, path, mock=False):
    if mock:
        media.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                   f"testsrc2=s=1280x720", "-frames:v", "1", str(path)])
        return path
    if media.ai_image(ART + prompt, path, seed=random.randint(1, 10**6), width=1280, height=720):
        LAST_IMG[0] = path
        return path
    return LAST_IMG[0]          # failed -> reuse the previous picture with a new camera move


MOVES = [  # slow, calm documentary camera moves (zoom expr, x expr, y expr)
    ("min(1+0.0006*on,1.18)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),            # slow push in
    ("max(1.18-0.0006*on,1)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),            # slow pull out
    ("1.15", "(iw-iw/zoom)*on/{f}", "ih/2-(ih/zoom/2)"),                         # pan right
    ("1.15", "(iw-iw/zoom)*(1-on/{f})", "ih/2-(ih/zoom/2)"),                     # pan left
    ("1.15", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{f})"),                     # tilt up
]


def scene_video(img, dur, idx, out):
    frames = int(dur * FPS) + 1
    if img is None:
        media.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                   f"color=c=0x2b2118:s={W}x{H}:r={FPS}:d={dur:.3f}",
                   "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", str(out)])
        return
    z, x, y = (m.format(f=frames) for m in MOVES[idx % len(MOVES)])
    vf = (f"scale={int(W * 1.5)}:{int(H * 1.5)}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={int(W * 1.5)}:{int(H * 1.5)},"
          f"zoompan=z='{z}':d={frames}:x='{x}':y='{y}':s={W}x{H}:fps={FPS},"
          f"setsar=1,format=yuv420p")
    media.run(["ffmpeg", "-y", "-v", "error", "-i", str(img), "-vf", vf,
               "-frames:v", str(frames), "-t", f"{dur:.3f}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-an", str(out)])


# ---------------- thumbnail ----------------
def thumbnail(script, work, mock=False):
    base = work / "thumb_base.jpg"
    prompt = ("Vibrant detailed hand-drawn illustration, bold colors, epic and dramatic, "
              "clean linework, simple bright sky in the top third, no text. "
              + script.get("thumbnail_scene", script["title"]))
    if mock or not media.ai_image(prompt, base, seed=random.randint(1, 10**6), width=1280, height=720):
        media.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720",
                   "-frames:v", "1", str(base)])
    ass = work / "thumb.ass"
    text = script.get("thumbnail_text") or script["title"]
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: T,{config.FONT_NAME},118,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,9,4,8,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,T,,0,0,0,,{text}
""", encoding="utf-8")
    out = work / "thumbnail.jpg"
    media.run(["ffmpeg", "-y", "-v", "error", "-i", str(base), "-vf",
               f"scale=1280:720,ass={ass.resolve()}", "-frames:v", "1", "-q:v", "3", str(out)])
    return out


# ---------------- subtitles (optional) ----------------
def subtitles_ass(scenes, durs, path):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: S,{config.FONT_NAME},50,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,160,160,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines, t = [], 0.0
    for sc, d in zip(scenes, durs):
        words = sc["narration"].split()
        parts = [" ".join(words[i:i + 9]) for i in range(0, len(words), 9)] or [""]
        w = [len(p) for p in parts]
        ct = t
        for p, n in zip(parts, w):
            pd = d * n / sum(w)
            lines.append(f"Dialogue: 0,{media._ts(ct)},{media._ts(ct + pd)},S,,0,0,0,,{p}")
            ct += pd
        t += d
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def fmt_ts(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


# ---------------- build ----------------
def build(script, work, mock=False):
    scenes, chapter_starts, t = [], [], 0.0
    voices, durs = [], []
    k = 0
    for ch in script["chapters"]:
        chapter_starts.append((t, ch["title"]))
        for sc in ch["scenes"]:
            raw, vp = work / f"v{k:03d}.mp3", work / f"v{k:03d}.wav"
            if mock:
                media.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=200:d=2.5", str(raw)])
            else:
                media.tts(sc["narration"], raw, rate=VOICE_RATE)
            # small natural pause after every scene
            media.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af", "apad=pad_dur=0.35",
                       "-ar", "44100", "-ac", "1", str(vp)])
            d = media.duration(vp)
            voices.append(vp)
            durs.append(d)
            scenes.append(sc)
            t += d
            k += 1
    total = sum(durs)
    print(f"  narration: {len(scenes)} scenes, {total / 60:.1f} minutes")

    clips = []
    for k, (sc, d) in enumerate(zip(scenes, durs)):
        img = picture(sc["visual"], work / f"img{k:03d}.jpg", mock)
        c = work / f"c{k:03d}.mp4"
        scene_video(img, d, k, c)
        clips.append(c)
        if k % 20 == 0:
            print(f"  pictures + camera moves: {k + 1}/{len(scenes)}")

    lst = work / "clips.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    visuals = work / "visuals.mp4"
    media.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
               "-c", "copy", str(visuals)])
    alst = work / "voices.txt"
    alst.write_text("".join(f"file '{v.resolve()}'\n" for v in voices))
    voice = work / "voice.wav"
    media.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(alst), str(voice)])

    vf = "null"
    if SUBTITLES:
        sub = work / "subs.ass"
        subtitles_ass(scenes, durs, sub)
        vf = f"ass={sub.resolve()}"
    music = sorted((ROOT / "assets" / "music").glob("*.mp3"))
    final = OUT / f"long-{dt.datetime.now(IST):%Y%m%d-%H%M}-{re.sub(r'[^a-z0-9]+', '-', script['topic_en'].lower()).strip('-')[:40]}.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(visuals), "-i", str(voice)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(random.choice(music))]
        fc = (f"[0:v]{vf}[v];[2:a]volume=0.07[m];[1:a][m]amix=inputs=2:duration=first:"
              "dropout_transition=0,loudnorm=I=-15:TP=-1.5[a]")
    else:
        fc = f"[0:v]{vf}[v];[1:a]loudnorm=I=-15:TP=-1.5[a]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(final)]
    media.run(cmd)

    # YouTube chapters: first must be 0:00, each at least 10 s
    chap_lines, last = [], -999
    for start, title in chapter_starts:
        if start - last >= 10 or not chap_lines:
            chap_lines.append(f"{fmt_ts(0 if not chap_lines else start)} {title}")
            last = start
    return final, chap_lines


def preview(video, thumb):
    """Contact sheet so the result can be checked without downloading the video."""
    try:
        d = media.duration(video)
        p = video.with_suffix(".preview.jpg")
        media.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf",
                   f"fps={12 / d:.5f},scale=320:-1,tile=4x3", "-frames:v", "1", str(p)])
        import shutil
        shutil.copy(thumb, video.with_suffix(".thumb.preview.jpg"))
    except Exception as e:
        print(f"  (preview skipped: {e})")


def next_publish_time():
    h, m = map(int, PUBLISH_TIME_IST.split(":"))
    now = dt.datetime.now(IST)
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if t < now + dt.timedelta(minutes=45):
        t += dt.timedelta(days=1)
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--topic", default=os.environ.get("LONG_TOPIC", "").strip() or None)
    args = ap.parse_args()
    if args.mock:
        args.no_upload = True

    OUT.mkdir(exist_ok=True)
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    script = mock_script() if args.mock else write_long_script([h["topic"] for h in history], args.topic)
    work = OUT / "long_work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")

    final, chapters = build(script, work, args.mock)
    thumb = thumbnail(script, work, args.mock)
    preview(final, thumb)
    print(f"VIDEO READY: {final.name} ({media.duration(final) / 60:.1f} min)")

    desc = (f"{script['description']}\n\n" + "\n".join(chapters) +
            "\n\nइस वीडियो के चित्र AI की मदद से बनाए गए हैं।\n#history #hindi #documentary")
    (work / "description.txt").write_text(desc, encoding="utf-8")
    print(desc)

    video_id = None
    if not args.no_upload:
        from uploader import set_thumbnail, upload
        when = next_publish_time() if config.AUTO_PUBLISH else None
        video_id = upload(final, script["title"], desc, script.get("tags", []), when, shorts=False)
        print(f"  uploaded https://youtu.be/{video_id}" + (f" (goes live {when} UTC)" if when else " (private draft)"))
        try:
            set_thumbnail(video_id, thumb)
            print("  thumbnail set")
        except Exception as e:
            print(f"  thumbnail not set (verify your channel's phone number to allow custom thumbnails): {e}")
    if not args.mock:
        history.append({"topic": script["topic_en"], "title": script["title"], "id": video_id,
                        "date": dt.date.today().isoformat()})
        HISTORY.parent.mkdir(exist_ok=True)
        HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
