# Runs on a FREE Kaggle GPU (T4 x2). Do not run on GitHub.
# Paints one illustration per scene with the open-source SDXL model, all in the
# same hand-drawn style, and saves them as /kaggle/working/<id>.jpg.
# GitHub inserts the job list at the line "JOBS = []" before pushing this script.
import json
import os
import subprocess
import sys
import time

JOBS = []  # replaced automatically
SETTINGS = {}  # replaced automatically

OUT = "/kaggle/working"
MODEL = SETTINGS.get("model", "stabilityai/stable-diffusion-xl-base-1.0")
VAE = "madebyollin/sdxl-vae-fp16-fix"          # stops black images in fp16
W = SETTINGS.get("width", 1344)                # SDXL's native 16:9 size
H = SETTINGS.get("height", 768)
STEPS = SETTINGS.get("steps", 28)
GUIDANCE = SETTINGS.get("guidance", 6.5)
BUDGET_MIN = SETTINGS.get("budget_minutes", 150)
STYLE = SETTINGS.get("style", "ink and watercolor illustration, graphic novel art, clean linework, "
                              "warm earthy colors, detailed, cinematic")
NEG = SETTINGS.get("negative", "photo, photorealistic, 3d render, cgi, text, letters, words, "
                               "watermark, signature, logo, blurry, lowres, jpeg artifacts, "
                               "deformed, bad anatomy, extra fingers, mutated hands, "
                               "extra limbs, ugly, disfigured, frame, border")
START = time.time()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def pip_setup():
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                    "diffusers>=0.30", "transformers>=4.44", "accelerate"], check=False)


def download():
    """Fetch the model once (both GPU workers then read it from the cache)."""
    from huggingface_hub import snapshot_download
    for attempt in range(3):
        try:
            snapshot_download(MODEL, allow_patterns=["*.json", "*.txt", "*fp16.safetensors"])
            snapshot_download(VAE, allow_patterns=["*.json", "diffusion_pytorch_model.safetensors"])
            log("model downloaded")
            return
        except Exception as e:
            log("download retry", attempt + 1, e)
            time.sleep(30)
    raise RuntimeError("model download failed")


def load_pipe():
    import torch
    from diffusers import AutoencoderKL, DPMSolverMultistepScheduler, StableDiffusionXLPipeline
    vae = AutoencoderKL.from_pretrained(VAE, torch_dtype=torch.float16)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        MODEL, vae=vae, torch_dtype=torch.float16, variant="fp16", use_safetensors=True)
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config, use_karras_sigmas=True)
    pipe.to("cuda")
    pipe.set_progress_bar_config(disable=True)
    return pipe


def worker(gpu, n_gpus):
    import numpy as np
    import torch

    mine = [j for k, j in enumerate(JOBS) if k % n_gpus == gpu]
    pipe = load_pipe()
    log(f"gpu{gpu}: model loaded, {len(mine)} pictures to paint")
    for j in mine:
        if (time.time() - START) / 60 > BUDGET_MIN:
            log(f"gpu{gpu}: time budget used, stopping")
            break
        dst = f"{OUT}/{j['id']}.jpg"
        style = j.get("style") or STYLE
        scene = j["prompt"]
        t0 = time.time()
        for attempt in range(2):
            try:
                with torch.no_grad():
                    img = pipe(
                        # each SDXL text encoder reads only ~75 words, so give both
                        # the style and the scene, in a different order
                        prompt=f"{style}, {scene}",
                        prompt_2=f"{scene}, {style}",
                        negative_prompt=NEG, negative_prompt_2=NEG,
                        width=W, height=H, num_inference_steps=STEPS,
                        guidance_scale=GUIDANCE,
                        generator=torch.Generator("cuda").manual_seed(j["seed"] + attempt * 7919),
                    ).images[0]
                arr = np.asarray(img, dtype=np.float32)
                if not np.isfinite(arr).all() or arr.std() < 4:
                    raise ValueError("blank picture")
                img.save(dst, quality=92)
                log(f"gpu{gpu}: {j['id']} done in {time.time() - t0:.0f}s")
                break
            except Exception as e:
                log(f"gpu{gpu}: {j['id']} attempt {attempt + 1} failed: {e}")
                torch.cuda.empty_cache()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(int(sys.argv[2]), int(sys.argv[3]))
        sys.exit(0)

    json.dump(JOBS, open(f"{OUT}/jobs.json", "w"))
    log(f"{len(JOBS)} pictures to paint")
    pip_setup()
    import torch
    n_gpus = torch.cuda.device_count()
    if n_gpus == 0:
        sys.exit("NO GPU: verify your phone number on Kaggle so the free GPU can be used")
    log("GPUs:", n_gpus, [torch.cuda.get_device_name(i) for i in range(n_gpus)])
    download()

    me = os.path.abspath(sys.argv[0] if sys.argv[0].endswith(".py") else __file__)
    procs = []
    for g in range(n_gpus):
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(g))
        procs.append(subprocess.Popen([sys.executable, me, "--worker", str(g), str(n_gpus)], env=env))
    for p in procs:
        p.wait()
    made = len([f for f in os.listdir(OUT) if f.endswith(".jpg")])
    log(f"FINISHED: {made}/{len(JOBS)} pictures in {(time.time() - START) / 60:.0f} min")
