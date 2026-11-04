"""Voice, visuals, subtitles and final video assembly."""
import asyncio
import json
import pathlib
import random
import subprocess
import time
import urllib.parse

import edge_tts
import requests

import config

ROOT = pathlib.Path(__file__).parent


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd[:6])}...\n{p.stderr[-1500:]}")
    return p.stdout


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "json", str(path)])
    return float(json.loads(out)["format"]["duration"])


# ---------------- Voice ----------------
def tts(text, out_path, rate=None):
    async def _go():
        await edge_tts.Communicate(text, config.VOICE, rate=rate or config.VOICE_RATE).save(str(out_path))
    for attempt in range(3):
        try:
            asyncio.run(_go())
            return duration(out_path)
        except Exception as e:  # network hiccup
            print(f"  tts retry {attempt + 1}: {e}")
            time.sleep(5)
    raise RuntimeError("voice generation failed")


# ---------------- Visuals ----------------
def ai_video(prompt, out_path):
    """Text-to-video on Replicate. Returns True on success."""
    if not config.REPLICATE_API_TOKEN:
        return False
    headers = {"Authorization": f"Bearer {config.REPLICATE_API_TOKEN}",
               "Content-Type": "application/json", "Prefer": "wait=60"}
    url = f"https://api.replicate.com/v1/models/{config.REPLICATE_MODEL}/predictions"
    for inputs in ({"prompt": prompt, **config.REPLICATE_EXTRA}, {"prompt": prompt}):
        r = requests.post(url, headers=headers, json={"input": inputs}, timeout=120)
        if r.status_code == 422:      # model doesn't accept an extra input -> try plain
            continue
        if r.status_code >= 400:
            print(f"  replicate error {r.status_code}: {r.text[:300]}")
            return False
        pred = r.json()
        deadline = time.time() + 900
        while pred["status"] not in ("succeeded", "failed", "canceled"):
            if time.time() > deadline:
                return False
            time.sleep(6)
            pred = requests.get(pred["urls"]["get"], headers=headers, timeout=60).json()
        if pred["status"] != "succeeded":
            print(f"  replicate {pred['status']}: {str(pred.get('error'))[:300]}")
            return False
        output = pred["output"]
        link = output[0] if isinstance(output, list) else output
        out_path.write_bytes(requests.get(link, timeout=300).content)
        return True
    return False


def ai_image(prompt, out_path, seed):
    """Free AI image (Pollinations). Returns True on success."""
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:900])
           + f"?width=1080&height=1920&nologo=true&seed={seed}")
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=240)
            if r.ok and r.headers.get("content-type", "").startswith("image") and len(r.content) > 20000:
                out_path.write_bytes(r.content)
                time.sleep(10)          # free service allows ~1 image per few seconds
                return True
            print(f"  image try {attempt + 1}: HTTP {r.status_code}")
        except requests.RequestException as e:
            print(f"  image try {attempt + 1}: {type(e).__name__}")
        time.sleep(20 * (attempt + 1))
    return False


LAST_IMAGE = None   # reused (with a new camera move) if an image fails


VF_FIT = (f"scale={config.W}:{config.H}:force_original_aspect_ratio=increase,"
          f"crop={config.W}:{config.H},fps={config.FPS},setsar=1,format=yuv420p")
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-an"]


def fit_clip(src, dur, out):
    """Turns an AI clip of any length into exactly `dur` seconds of 1080x1920.
    Short clips are slowed down a little (max 1.6x), then the last frame is held."""
    src_d = duration(src)
    slow = min(max(dur / max(src_d, 0.1), 1.0), 1.6)
    vf = (f"setpts={slow:.4f}*PTS,"
          f"scale={config.W}:{config.H}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={config.W}:{config.H},unsharp=5:5:0.6,fps={config.FPS},"
          f"tpad=stop_mode=clone:stop_duration={dur + 1:.2f},setsar=1,format=yuv420p")
    run(["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-t", f"{dur:.3f}", *ENC, str(out)])


def scene_clip(visual_prompt, dur, use_ai_video, work, idx, kaggle_clip=None, kaggle_image=None):
    """Makes an exactly `dur`-second 1080x1920 silent clip for one scene."""
    out = work / f"scene_{idx:02d}.mp4"
    raw_vid, raw_img = work / f"raw_{idx:02d}.mp4", work / f"raw_{idx:02d}.jpg"
    global LAST_IMAGE

    if kaggle_clip:                       # free animated clip from Kaggle GPU
        try:
            fit_clip(kaggle_clip, dur, out)
            if kaggle_image:
                LAST_IMAGE = kaggle_image
            return out, "kaggle-video"
        except Exception as e:
            print(f"  kaggle clip unusable: {e}")

    if kaggle_image:                      # image made, animation missing -> camera move
        LAST_IMAGE = kaggle_image
        kenburns(kaggle_image, dur, idx, out)
        return out, "kaggle-image"

    if use_ai_video and ai_video(visual_prompt, raw_vid):
        fit_clip(raw_vid, dur, out)
        return out, "ai-video"

    if ai_image(visual_prompt, raw_img, seed=random.randint(1, 10**6)):
        LAST_IMAGE = raw_img
        kenburns(raw_img, dur, idx, out)
        return out, "ai-image"

    if LAST_IMAGE is not None:      # reuse the previous scene's picture, new camera move
        kenburns(LAST_IMAGE, dur, idx + 1, out)
        return out, "reused-image"

    # last resort so the run never dies: animated gradient background
    run(["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"gradients=s={config.W}x{config.H}:speed=0.02:r={config.FPS}:d={dur:.3f}",
         "-vf", "format=yuv420p", *ENC, str(out)])
    return out, "fallback"


def kenburns(img, dur, idx, out):
    frames = int(dur * config.FPS) + 1
    # rotate between 4 camera moves so scenes feel animated, not like a slideshow
    moves = [
        ("min(1+0.0012*on,1.3)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),      # push in
        ("max(1.3-0.0012*on,1)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),      # pull out
        ("1.2", f"(iw-iw/zoom)*on/{frames}", "ih/2-(ih/zoom/2)"),              # pan right
        ("1.2", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-on/{frames})"),          # tilt up
    ]
    z, x, y = moves[idx % len(moves)]
    vf = (f"scale={config.W * 2}:{config.H * 2}:force_original_aspect_ratio=increase,"
          f"crop={config.W * 2}:{config.H * 2},"
          f"zoompan=z='{z}':d={frames}:x='{x}':y='{y}'"
          f":s={config.W}x{config.H}:fps={config.FPS},setsar=1,format=yuv420p")
    run(["ffmpeg", "-y", "-i", str(img), "-vf", vf, "-frames:v", str(frames),
         "-t", f"{dur:.3f}", *ENC, str(out)])


# ---------------- Subtitles ----------------
def _ts(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def write_ass(scenes, durations, out_path):
    """Big bold captions, 3 words at a time, like most viral shorts."""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.W}
PlayResY: {config.H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{config.FONT_NAME},92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,2,70,70,520,1
Style: Hook,{config.FONT_NAME},96,&H0000E5FF,&H0000E5FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,8,3,2,70,70,520,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines, t = [], 0.0
    for i, (sc, d) in enumerate(zip(scenes, durations)):
        words = sc["narration"].split()
        chunks = [" ".join(words[j:j + 3]) for j in range(0, len(words), 3)] or [""]
        weights = [max(len(c), 1) for c in chunks]
        total, ct = sum(weights), t
        for c, w in zip(chunks, weights):
            cd = d * w / total
            style = "Hook" if i == 0 else "Cap"
            lines.append(f"Dialogue: 0,{_ts(ct)},{_ts(ct + cd)},{style},,0,0,0,,"
                         r"{\fad(60,0)\t(0,120,\fscx108\fscy108)\t(120,220,\fscx100\fscy100)}" + c)
            ct += cd
        t += d
    out_path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


# ---------------- Final assembly ----------------
def assemble(clips, voices, ass_path, out_path, work):
    lst = work / "clips.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    visuals = work / "visuals.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(visuals)])

    alst = work / "voices.txt"
    alst.write_text("".join(f"file '{v.resolve()}'\n" for v in voices))
    voice = work / "voice.wav"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(alst), "-ar", "44100", str(voice)])

    music = sorted((ROOT / "assets" / "music").glob("*.mp3"))
    sub = f"ass={ass_path.resolve()}"
    cmd = ["ffmpeg", "-y", "-i", str(visuals), "-i", str(voice)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(random.choice(music))]
        fc = (f"[0:v]{sub}[v];[2:a]volume={config.MUSIC_VOLUME}[m];"
              "[1:a][m]amix=inputs=2:duration=first:dropout_transition=0,"
              "loudnorm=I=-14:TP=-1.5[a]")
    else:
        fc = f"[0:v]{sub}[v];[1:a]loudnorm=I=-14:TP=-1.5[a]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(out_path)]
    run(cmd)
    return out_path
