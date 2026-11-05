"""Sends work to a free Kaggle GPU (animated clips for shorts, or painted
pictures for documentaries), waits, and downloads the results.

Needs the GitHub secret KAGGLE_API_TOKEN (Kaggle > Settings > API > Generate New Token).
If anything goes wrong, it returns what it has and the bot falls back to
animated still images, so the daily videos are never lost."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import time

ROOT = pathlib.Path(__file__).parent
SLUG = "hindi-shorts-animator"


def enabled():
    return bool(os.environ.get("KAGGLE_API_TOKEN", "").strip())


def _kaggle(*args, timeout=600):
    p = subprocess.run(["kaggle", *args], capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def _username():
    if os.environ.get("KAGGLE_USERNAME"):
        return os.environ["KAGGLE_USERNAME"].strip()
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    api.authenticate()
    return api.config_values.get("username")


def _run_kernel(slug, worker_file, jobs, settings, out_dir, max_wait_min):
    """Pushes kaggle_worker/<worker_file> with the jobs inside, waits, downloads the output.
    Returns (download_folder, final_status)."""
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    user = _username()
    kid = f"{user}/{slug}"
    print(f"  kaggle: account {user}, {len(jobs)} jobs ({worker_file})")

    code_rc, quota = _kaggle("quota")
    if code_rc == 0:
        print("  kaggle quota:", " ".join(quota.split())[:300])

    folder = out_dir / "kernel"
    folder.mkdir(exist_ok=True)
    src = (ROOT / "kaggle_worker" / worker_file).read_text(encoding="utf-8")
    src = src.replace("JOBS = []  # replaced automatically",
                      "JOBS = " + json.dumps(jobs, ensure_ascii=True), 1)
    src = src.replace("SETTINGS = {}  # replaced automatically",
                      "SETTINGS = " + json.dumps(settings), 1)
    (folder / worker_file).write_text(src, encoding="utf-8")
    (folder / "kernel-metadata.json").write_text(json.dumps({
        "id": kid, "title": slug, "code_file": worker_file,
        "language": "python", "kernel_type": "script", "is_private": True,
        "enable_gpu": True, "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [], "competition_sources": [], "kernel_sources": [],
    }, indent=1))

    rc, msg = _kaggle("kernels", "push", "-p", str(folder), "--accelerator", "NvidiaTeslaT4")
    print("  kaggle push:", msg[-400:])
    if rc != 0 or "error" in msg.lower() and "successfully" not in msg.lower():
        raise RuntimeError("kaggle push failed: " + msg[-400:])

    time.sleep(45)
    deadline = time.time() + max_wait_min * 60
    status, last = "", ""
    while time.time() < deadline:
        rc, msg = _kaggle("kernels", "status", kid, timeout=120)
        m = re.search(r'status "?([A-Za-z_.]+)', msg)
        status = (m.group(1) if m else msg).lower()
        if status != last:
            print(f"  kaggle status: {status}  ({time.strftime('%H:%M')})")
            last = status
        if any(s in status for s in ("complete", "error", "cancel")):
            break
        time.sleep(30)
    else:
        print("  kaggle: still running at our deadline, downloading what exists")

    dl = out_dir / "kaggle_out"
    shutil.rmtree(dl, ignore_errors=True)
    dl.mkdir()
    rc, msg = _kaggle("kernels", "output", kid, "-p", str(dl), "-o", timeout=1800)
    print("  kaggle download:", msg[-300:])
    for log in list(dl.rglob("*.log")) + list(dl.rglob("*.txt")):
        text = log.read_text(errors="ignore")
        print(f"  ---- kaggle log ({log.name}), last lines ----")
        print("\n".join(text.splitlines()[-60:]))
    return dl, status


def animate(jobs, out_dir, settings, max_wait_min=300):
    """Shorts: jobs = [{id, image_prompt, video_prompt, seed}] -> {id: {"clip", "image"}}."""
    if not jobs:
        return {}
    dl, status = _run_kernel(SLUG, "animate.py", jobs, settings, out_dir, max_wait_min)
    result = {}
    for j in jobs:
        clip = next(iter(dl.rglob(f"{j['id']}.mp4")), None)
        img = next(iter(dl.rglob(f"{j['id']}.jpg")), None)
        result[j["id"]] = {"clip": clip, "image": img}
    got = sum(1 for r in result.values() if r["clip"])
    print(f"  kaggle: {got}/{len(jobs)} clips received (status: {status})")
    return result


def paint(jobs, out_dir, settings, max_wait_min=150):
    """Documentaries: jobs = [{id, prompt, seed, style?}] -> {id: picture path}.
    Missing pictures are simply absent (the caller falls back to other sources)."""
    if not jobs:
        return {}
    dl, status = _run_kernel("hindi-docu-painter", "paint.py", jobs, settings, out_dir, max_wait_min)
    result = {}
    for j in jobs:
        img = next(iter(dl.rglob(f"{j['id']}.jpg")), None)
        if img and img.stat().st_size > 20000:
            result[j["id"]] = img
    print(f"  kaggle: {len(result)}/{len(jobs)} pictures received (status: {status})")
    return result
