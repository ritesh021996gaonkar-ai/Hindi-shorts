"""All settings live here. Every value can be overridden with an environment
variable (GitHub Actions secrets / variables), so you never need to edit code."""
import json
import os


def env(name, default=""):
    v = os.environ.get(name, "")
    return v if v.strip() else default


# ---------- API keys (put these in GitHub Secrets) ----------
GEMINI_API_KEY = env("GEMINI_API_KEY")          # free key: aistudio.google.com
REPLICATE_API_TOKEN = env("REPLICATE_API_TOKEN")  # OPTIONAL, only for paid AI video clips
YT_CLIENT_ID = env("YT_CLIENT_ID")
YT_CLIENT_SECRET = env("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = env("YT_REFRESH_TOKEN")

# ---------- Channel style ----------
CHANNEL_NAME = env("CHANNEL_NAME", "Kya Hoga Agar?")
NICHE = env(
    "NICHE",
    "surprising science, human body, history and 'what would happen if' "
    "situations explained simply, told in second person (aap / tum)",
)

# ---------- Script writer (Gemini) ----------
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-flash-latest")  # auto-switches if unavailable

# ---------- AI video clips (Replicate) ----------
# Any Replicate text-to-video model works. Check replicate.com/collections/text-to-video
# for current names and prices, then set REPLICATE_MODEL in GitHub Variables.
REPLICATE_MODEL = env("REPLICATE_MODEL", "alibaba/wan-3")
# Extra inputs sent to the model (must match the model's input names on its page).
REPLICATE_EXTRA = json.loads(env("REPLICATE_EXTRA", '{"aspect_ratio": "9:16"}'))
# How many scenes per video get a real AI video clip. The rest use an AI image
# with slow zoom (almost free). This is the main COST knob.
AI_CLIPS_PER_VIDEO = int(env("AI_CLIPS_PER_VIDEO", "0"))   # 0 = FREE mode

# ---------- Voice ----------
VOICE = env("VOICE", "hi-IN-MadhurNeural")      # or hi-IN-SwaraNeural (female)
VOICE_RATE = env("VOICE_RATE", "+8%")

# ---------- Posting ----------
VIDEOS_PER_DAY = int(env("VIDEOS_PER_DAY", "5"))
POST_TIMES_IST = env("POST_TIMES_IST", "09:00,12:30,16:00,19:00,21:30").split(",")
# true  = schedule automatically at POST_TIMES_IST
# false = upload as private drafts, you review and publish yourself
AUTO_PUBLISH = env("AUTO_PUBLISH", "true").lower() == "true"

# ---------- Video ----------
W, H, FPS = 1080, 1920, 30
MUSIC_VOLUME = float(env("MUSIC_VOLUME", "0.10"))
FONT_NAME = "Noto Sans Devanagari"
