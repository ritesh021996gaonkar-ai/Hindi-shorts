# Runs on a FREE Kaggle GPU (T4 x2). Do not run on GitHub.
# For every scene: download an AI image that matches the narration, then animate
# it into a ~5 second video clip with the open-source LTX-Video model.
# GitHub inserts the job list at the line "JOBS = []" before pushing this script.
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.parse
import urllib.request

JOBS = []  # replaced automatically
SETTINGS = {}  # replaced automatically

OUT = "/kaggle/working"
TMP = "/kaggle/tmp"
W = SETTINGS.get("width", 480)
H = SETTINGS.get("height", 832)
FRAMES = SETTINGS.get("frames", 121)          # 121 frames = ~5 s at 24 fps (must be 8k+1)
STEPS = SETTINGS.get("steps", 30)
BUDGET_MIN = SETTINGS.get("budget_minutes", 200)   # stop starting new clips after this
NEG = "worst quality, inconsistent motion, blurry, jittery, distorted, deformed, text, watermark"
MODELS = [  # tried in order
    ("Lightricks/LTX-Video-0.9.5", "condition"),
    ("Lightricks/LTX-Video", "i2v"),
]
START = time.time()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def pip_setup():
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                    "diffusers>=0.35", "transformers>=4.48", "accelerate",
                    "sentencepiece", "imageio", "imageio-ffmpeg"], check=False)


# ---------------- 1. images ----------------
def fetch_image(job, path):
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(job["image_prompt"][:900])
           + f"?width=720&height=1280&nologo=true&seed={job['seed']}")
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "shorts-bot"})
            with urllib.request.urlopen(req, timeout=240) as r:
                data = r.read()
                if r.headers.get("content-type", "").startswith("image") and len(data) > 20000:
                    open(path, "wb").write(data)
                    return True
        except Exception as e:
            log("  image retry", attempt + 1, type(e).__name__, str(e)[:80])
        time.sleep(15 * (attempt + 1))
    return False


def get_images():
    os.makedirs(f"{OUT}/images", exist_ok=True)
    for j in JOBS:
        p = f"{OUT}/images/{j['id']}.jpg"
        if not os.path.exists(p):
            ok = fetch_image(j, p)
            log("image", j["id"], "ok" if ok else "FAILED (will use text-to-video)")
            time.sleep(6)


# ---------------- 2. text embeddings (once, then free the big encoder) ----------------
def encode_prompts(model_id, kind):
    import torch
    from transformers import T5EncoderModel, T5TokenizerFast
    tok = T5TokenizerFast.from_pretrained(model_id, subfolder="tokenizer")
    enc = None
    for dev, dt in (("cuda:0", torch.bfloat16), ("cpu", torch.bfloat16), ("cpu", torch.float32)):
        try:
            enc = T5EncoderModel.from_pretrained(model_id, subfolder="text_encoder",
                                                 torch_dtype=dt).to(dev)
            test = embed(tok, enc, dev, ["test"])[0]
            if torch.isfinite(test).all():
                log("text encoder on", dev, dt)
                break
        except Exception as e:
            log("text encoder failed on", dev, dt, e)
        enc = None
    if enc is None:
        raise RuntimeError("could not load text encoder")
    texts = [j["video_prompt"] for j in JOBS] + [NEG]
    out = {}
    for t in texts:
        e, m = embed(tok, enc, enc.device, [t])
        out[t] = (e.cpu().to(torch.float32), m.cpu())
    del enc
    torch.cuda.empty_cache()
    torch.save(out, f"{TMP}/emb.pt")


def embed(tok, enc, dev, texts):
    import torch
    t = tok(texts, padding="max_length", max_length=256, truncation=True,
            add_special_tokens=True, return_tensors="pt")
    with torch.no_grad():
        e = enc(t.input_ids.to(dev), attention_mask=t.attention_mask.to(dev))[0]
    return e, t.attention_mask


# ---------------- 3. animation (one process per GPU) ----------------
def worker(gpu, n_gpus):
    import numpy as np
    import torch
    from diffusers.utils import export_to_video
    from PIL import Image

    emb = torch.load(f"{TMP}/emb.pt")
    mine = [j for k, j in enumerate(JOBS) if k % n_gpus == gpu]
    pipe, kind, dtype = None, None, None
    for model_id, kind in MODELS:
        for dtype in (torch.float16, torch.bfloat16):
            try:
                pipe = load_pipe(model_id, kind, dtype)
                log(f"gpu{gpu}: loaded {model_id} {dtype}")
                break
            except Exception as e:
                log(f"gpu{gpu}: load failed {model_id} {dtype}: {e}")
                pipe = None
        if pipe:
            break
    if pipe is None:
        raise RuntimeError("no video model could be loaded")

    os.makedirs(f"{OUT}/clips", exist_ok=True)
    for j in mine:
        if (time.time() - START) / 60 > BUDGET_MIN:
            log(f"gpu{gpu}: time budget used, stopping")
            break
        dst = f"{OUT}/clips/{j['id']}.mp4"
        img_path = f"{OUT}/images/{j['id']}.jpg"
        image = None
        if os.path.exists(img_path):
            image = Image.open(img_path).convert("RGB").resize((W, H), Image.LANCZOS)
        pe, pm = emb[j["video_prompt"]]
        ne, nm = emb[NEG]
        t0 = time.time()
        for attempt in range(2):
            try:
                frames = run_pipe(pipe, kind, image, pe, pm, ne, nm, j["seed"] + attempt)
                arr = np.asarray(frames[len(frames) // 2], dtype=np.float32)
                if not np.isfinite(arr).all() or arr.std() < 3:      # black / broken output
                    raise ValueError("blank frames (fp16 overflow?)")
                export_to_video(frames, dst, fps=24)
                log(f"gpu{gpu}: clip {j['id']} done in {time.time() - t0:.0f}s")
                break
            except Exception as e:
                log(f"gpu{gpu}: clip {j['id']} attempt {attempt + 1} failed: {e}")
                if "blank" in str(e) and dtype == torch.float16:
                    del pipe
                    torch.cuda.empty_cache()
                    dtype = torch.bfloat16
                    pipe = load_pipe(*[m for m in MODELS if m[1] == kind][0], dtype)
                    log(f"gpu{gpu}: switched to bf16")
                torch.cuda.empty_cache()


def load_pipe(model_id, kind, dtype):
    import torch
    from diffusers import AutoencoderKLLTXVideo, LTXConditionPipeline, LTXImageToVideoPipeline
    cls = LTXConditionPipeline if kind == "condition" else LTXImageToVideoPipeline
    vae = AutoencoderKLLTXVideo.from_pretrained(model_id, subfolder="vae", torch_dtype=torch.float32)
    pipe = cls.from_pretrained(model_id, vae=vae, text_encoder=None, tokenizer=None,
                               torch_dtype=dtype)
    pipe.to("cuda")
    pipe.vae.enable_tiling()
    return pipe


def run_pipe(pipe, kind, image, pe, pm, ne, nm, seed):
    import torch
    dev, dt = "cuda", pipe.transformer.dtype
    args = dict(
        prompt_embeds=pe.to(dev, dt), prompt_attention_mask=pm.to(dev),
        negative_prompt_embeds=ne.to(dev, dt), negative_prompt_attention_mask=nm.to(dev),
        width=W, height=H, num_frames=FRAMES, num_inference_steps=STEPS,
        guidance_scale=3.0, decode_timestep=0.05, decode_noise_scale=0.025,
        generator=torch.Generator(device="cuda").manual_seed(seed), output_type="pil",
    )
    if image is not None:
        args["image"] = image
    elif kind == "i2v":            # i2v pipeline needs an image: use a plain frame
        from PIL import Image
        args["image"] = Image.new("RGB", (W, H), (40, 60, 90))
    with torch.no_grad():
        return pipe(**args).frames[0]


# ---------------- main ----------------
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(int(sys.argv[2]), int(sys.argv[3]))
        sys.exit(0)

    os.makedirs(TMP, exist_ok=True)
    json.dump(JOBS, open(f"{OUT}/jobs.json", "w"))
    log(f"{len(JOBS)} scenes to animate")
    pip_setup()
    get_images()
    import torch
    n_gpus = max(1, torch.cuda.device_count())
    log("GPUs:", n_gpus, [torch.cuda.get_device_name(i) for i in range(n_gpus)])

    done = False
    for model_id, kind in MODELS:
        try:
            encode_prompts(model_id, kind)
            done = True
            break
        except Exception:
            traceback.print_exc()
    if not done:
        sys.exit("text encoding failed")

    me = os.path.abspath(sys.argv[0] if sys.argv[0].endswith(".py") else __file__)
    procs = []
    for g in range(n_gpus):
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(g))
        procs.append(subprocess.Popen([sys.executable, me, "--worker", str(g), str(n_gpus)], env=env))
    for p in procs:
        p.wait()
    made = len(os.listdir(f"{OUT}/clips")) if os.path.isdir(f"{OUT}/clips") else 0
    log(f"FINISHED: {made}/{len(JOBS)} clips in {(time.time() - START) / 60:.0f} min")
