"""Daily pipeline: write script -> voice -> visuals -> captions -> video -> upload.

Usage:
  python main.py                 # make VIDEOS_PER_DAY shorts and upload/schedule them
  python main.py --count 1 --no-upload   # test: make 1 video, don't upload
  python main.py --mock          # offline test with fake script/voice/visuals
"""
import argparse
import datetime as dt
import json
import pathlib
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
            {"narration": "अगर आप पूरे एक हफ्ते तक बिल्कुल ना सोएं तो क्या होगा?", "visual": "x"},
            {"narration": "पहले ही दिन आपका दिमाग धीमा होने लगता है।", "visual": "x"},
            {"narration": "तीसरे दिन आपको ऐसी चीज़ें दिखने लगती हैं जो असल में हैं ही नहीं।", "visual": "x"},
        ],
    }


def make_one(i, history, args, work_root):
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

    clips, kinds = [], []
    for k, (sc, d) in enumerate(zip(scenes, durs)):
        if args.mock:
            c = work / f"scene_{k:02d}.mp4"
            media.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                       f"gradients=s={config.W}x{config.H}:r={config.FPS}:d={d:.3f}",
                       "-vf", "format=yuv420p", *media.ENC, str(c)])
            kind = "mock"
        else:
            c, kind = media.scene_clip(sc["visual"], d, k < config.AI_CLIPS_PER_VIDEO, work, k)
        clips.append(c)
        kinds.append(kind)
    print(f"    visuals: {', '.join(kinds)}")

    ass = work / "captions.ass"
    media.write_ass(scenes, durs, ass)
    final = OUT / f"{stamp}-{i}-{slug}.mp4"
    media.assemble(clips, voices, ass, final, work)
    print(f"    video ready: {final.name} ({media.duration(final):.1f}s)")
    return script, final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=config.VIDEOS_PER_DAY)
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()
    if args.mock:
        args.no_upload = True

    OUT.mkdir(exist_ok=True)
    history = load_history()
    slots = slot_times(args.count)
    made = 0
    for i in range(args.count):
        try:
            script, final = make_one(i, history, args, OUT / "work")
        except Exception:
            traceback.print_exc()
            print(f"[{i}] FAILED, moving on to the next video")
            continue

        video_id = None
        if not args.no_upload:
            from uploader import upload
            title = f"{script['title']} #shorts"
            desc = (f"{script['description']}\n\n"
                    "इस वीडियो के विज़ुअल्स AI की मदद से बनाए गए हैं।\n"
                    "#shorts #hindi #facts")
            when = slots[i] if config.AUTO_PUBLISH else None
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
