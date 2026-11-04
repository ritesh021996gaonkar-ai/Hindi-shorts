"""Daily pipeline:
  1. write all scripts + record Hindi voice
  2. make visuals: free Kaggle GPU animates a narration-matched AI image per scene
     (if Kaggle isn't set up or fails -> animated still images)
  3. captions + final video  4. upload / schedule

Usage:
  python main.py                         # make VIDEOS_PER_DAY shorts and upload them
  python main.py --count 1 --no-upload   # test: 1 video, no upload
  python main.py --no-kaggle             # skip Kaggle, still images only
  python main.py --mock                  # offline test with fake data
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
HISTORY = ROOT / "data" / "history.json"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def load_history():
    if HISTORY.exists():
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    return []


def save_history(h):
    HISTORY.parent.mkdir(exist_ok=True)
    HISTORY.write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")


def slot_times(n):
    """Next n posting times (IST), returned as UTC RFC3339 strings."""
    now = dt.datetime.now(IST)
    times = []
    day = now.date()
    while len(times) < n:
        for hm in config.POST_TIMES_IST:
            h, m = map(int, hm.strip().split(":"))
            t = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=IST)
            if t > now + dt.timedelta(minutes=30) and len(times) < n:
                times.append(t)
        day += dt.timedelta(days=1)
    return [t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") for t in times]


def mock_script(i):
    return {
        "topic_en": f"mock topic {i}",
        "title": "अगर आप 1 हफ्ता सोएं नहीं तो क्या होगा? 😴",
        "description": "जानिए नींद के बिना आपके दिमाग और शरीर के साथ क्या होता है।",
        "tags": ["hindi facts", "नींद", "science"],
        "scenes": [
            {"narration": "अगर आप पूरे एक हफ्ते तक बिल्कुल ना सोएं तो क्या होगा?", "visual": "x", "motion": "y"},
            {"narration": "पहले ही दिन आपका दिमाग धीमा होने लगता है।", "visual": "x", "motion": "y"},
            {"narration": "तीसरे दिन आपको ऐसी चीज़ें दिखने लगती हैं जो असल में हैं ही नहीं।", "visual": "x", "motion": "y"},
        ],
    }


# ---------- step 1: script + voice ----------
def prepare(i, history, args, work_root):
    from script_writer import write_script

    script = mock_script(i) if args.mock else write_script([h["topic"] for h in history])
    slug = re.sub(r"[^a-z0-9]+", "-", script["topic_en"].lower()).strip("-")[:40] or f"video-{i}"
    stamp = dt.datetime.now(IST).strftime("%Y%m%d-%H%M")
    work = work_root / f"{stamp}-{i}-{slug}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{i}] {script['title']}")

    scenes = script["scenes"]
    voices, durs = [], []
    for k, sc in enumerate(scenes):
        vp = work / f"voice_{k:02d}.mp3"
        if args.mock:
            media.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=f=220:d=3.2", str(vp)])
            d = media.duration(vp)
        else:
            d = media.tts(sc["narration"], vp)
        voices.append(vp)
        durs.append(d)

    # keep the short under ~58s: if the voice is too long, re-record a bit faster
    total = sum(durs)
    if not args.mock and total > 58:
        base = int(config.VOICE_RATE.strip("%+") or 0)
        rate = min(base + round((total / 56 - 1) * 100) + 2, 45)
        print(f"    voice {total:.0f}s too long, re-recording at +{rate}%")
        durs = [media.tts(sc["narration"], vp, rate=f"+{rate}%") for sc, vp in zip(scenes, voices)]

    return {"i": i, "script": script, "slug": slug, "stamp": stamp, "work": work,
            "voices": voices, "durs": durs}


def kaggle_jobs(videos):
    jobs = []
    for v in videos:
        for k, sc in enumerate(v["script"]["scenes"]):
            jobs.append({
                "id": f"v{v['i']}s{k:02d}",
                "image_prompt": sc.get("visual", ""),
                "video_prompt": (sc.get("visual", "") + " " + sc.get("motion", "")).strip(),
                "seed": random.randint(1, 10**6),
            })
    return jobs


# ---------- step 3: visuals + captions + final video ----------
def build(v, args, kaggle_res):
    scenes, durs, work = v["script"]["scenes"], v["durs"], v["work"]
    clips, kinds = [], []
    for k, (sc, d) in enumerate(zip(scenes, durs)):
        if args.mock:
            c = work / f"scene_{k:02d}.mp4"
            media.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                       f"gradients=s={config.W}x{config.H}:r={config.FPS}:d={d:.3f}",
                       "-vf", "format=yuv420p", *media.ENC, str(c)])
            kind = "mock"
        else:
            kr = kaggle_res.get(f"v{v['i']}s{k:02d}", {})
            c, kind = media.scene_clip(sc["visual"], d, k < config.AI_CLIPS_PER_VIDEO, work, k,
                                       kaggle_clip=kr.get("clip"), kaggle_image=kr.get("image"))
        clips.append(c)
        kinds.append(kind)
    print(f"[{v['i']}] visuals: {', '.join(kinds)}")

    ass = work / "captions.ass"
    media.write_ass(scenes, durs, ass)
    final = OUT / f"{v['stamp']}-{v['i']}-{v['slug']}.mp4"
    media.assemble(clips, v["voices"], ass, final, work)
    print(f"    video ready: {final.name} ({media.duration(final):.1f}s)")
    make_preview(final)
    return final


def make_preview(video):
    """Small contact sheet (6 frames) so the result can be checked without downloading."""
    try:
        d = media.duration(video)
        tiles = []
        for n in range(6):
            t = d * (n + 0.5) / 6
            p = video.with_name(f"{video.stem}_f{n}.jpg")
            media.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                       "-frames:v", "1", "-vf", "scale=270:-1", str(p)])
            tiles.append(p)
        ins = sum([["-i", str(p)] for p in tiles], [])
        media.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex",
                   f"hstack=inputs={len(tiles)}", str(video.with_suffix(".preview.jpg"))])
        for p in tiles:
            p.unlink()
    except Exception as e:
        print(f"    (preview skipped: {e})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=config.VIDEOS_PER_DAY)
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--no-kaggle", action="store_true")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()
    if args.mock:
        args.no_upload = args.no_kaggle = True

    OUT.mkdir(exist_ok=True)
    history = load_history()

    # 1. scripts + voices
    videos = []
    for i in range(args.count):
        try:
            videos.append(prepare(i, history, args, OUT / "work"))
            if not args.mock:   # don't write the same topic twice in one day
                history.append({"topic": videos[-1]["script"]["topic_en"], "title": "", "id": None,
                                "date": dt.date.today().isoformat(), "pending": True})
        except Exception:
            traceback.print_exc()
            print(f"[{i}] script/voice FAILED, skipping this video")
    history = [h for h in history if not h.get("pending")]

    # 2. animated clips on the free Kaggle GPU
    kaggle_res = {}
    import kaggle_runner
    if videos and not args.no_kaggle and kaggle_runner.enabled():
        try:
            settings = {"steps": int(os.environ.get("KAGGLE_STEPS") or 30),
                        "budget_minutes": int(os.environ.get("KAGGLE_BUDGET_MIN") or 200)}
            kaggle_res = kaggle_runner.animate(kaggle_jobs(videos), OUT / "kaggle", settings)
        except Exception:
            traceback.print_exc()
            print("Kaggle step failed -> using animated still images instead")
    elif not args.mock:
        print("Kaggle not set up (no KAGGLE_API_TOKEN) -> using animated still images")

    # 3 + 4. build and upload
    made = 0
    slots = slot_times(len(videos))
    for n, v in enumerate(videos):
        try:
            final = build(v, args, kaggle_res)
        except Exception:
            traceback.print_exc()
            print(f"[{v['i']}] FAILED while building, moving on")
            continue
        script = v["script"]
        video_id = None
        if not args.no_upload:
            from uploader import upload
            title = f"{script['title']} #shorts"
            desc = (f"{script['description']}\n\n"
                    "इस वीडियो के विज़ुअल्स AI की मदद से बनाए गए हैं।\n"
                    "#shorts #hindi #facts")
            when = slots[n] if config.AUTO_PUBLISH else None
            video_id = upload(final, title, desc, script.get("tags", []), when)
            print(f"    uploaded https://youtube.com/shorts/{video_id}"
                  + (f" (goes live {when} UTC)" if when else " (private draft)"))
        if not args.mock:
            history.append({"topic": script["topic_en"], "title": script["title"],
                            "id": video_id, "date": dt.date.today().isoformat()})
            save_history(history)
        made += 1

    print(f"Done: {made}/{args.count} videos")
    if made == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
