# Hindi Shorts Bot (FREE version): 5 Hindi explainer shorts a day

Every night at 2 AM IST, this bot makes 5 original Hindi shorts and schedules them on your channel.
The default posting times are 9:00, 12:30, 16:00, 19:00 and 21:30.
**It costs ₹0.**

**How each short is made:**
1. **Script:** Gemini (free) writes a new Hindi "Kya hoga agar…" script, about 150 words long. It never repeats a past topic.
2. **Voice:** a natural Hindi voice is generated for free with Microsoft Edge TTS.
3. **Visuals:** each scene gets a free 3D-style AI image with a moving camera (push in, pull out, pan, tilt), so it feels animated.
4. **Captions:** bold Hindi captions are added, 3 words at a time, with the hook in yellow.
5. **Upload:** the finished 1080×1920 video goes to YouTube with its title and tags, and is scheduled. It is marked "AI-generated", as YouTube requires.

The mascot is **Chotu**, a small teal robot that belongs to your channel.

---

## Setup from your phone (about 45 minutes)
Tip: in Chrome, tap ⋮ and turn on **Desktop site** for the Google Cloud and GitHub pages.

### 1. Free Gemini key
1. Go to https://aistudio.google.com and choose **Get API key → Create API key**.
2. Copy the key and save it in your notes.

### 2. GitHub (runs the bot every day, free)
1. Sign up at https://github.com.
2. Create a new **public** repository called `hindi-shorts`. Public repos get unlimited free run time.
3. In the Claude app, go to **Settings → Connectors** and connect GitHub. Claude will put the code in the repo for you.

### 3. YouTube upload permission (Google Cloud)
1. Go to https://console.cloud.google.com and create a new project called "shorts bot".
2. Under **APIs & Services → Library**, search **YouTube Data API v3** and tap **Enable**.
3. Under **OAuth consent screen**, fill it in:
   - User type: External
   - App name: Shorts Bot
   - Use your Gmail for the contact fields
   - Add your Gmail as a **test user**
4. Back on the **OAuth consent screen**, tap **PUBLISH APP** and confirm, so it says "In production".
   - **Important:** if you skip this, your login stops working every 7 days.
5. Under **Credentials**, choose **Create credentials → OAuth client ID**, then fill in:
   - Application type: **Web application**
   - Authorized redirect URI: `https://developers.google.com/oauthplayground`
6. Tap **Create**, then copy the **Client ID** and **Client secret**.

### 4. Get your YouTube login token (OAuth Playground)
1. Go to https://developers.google.com/oauthplayground.
2. Tap the ⚙️ gear (top right) and tick **Use your own OAuth credentials**. Paste your Client ID and Client secret.
3. In the left box ("Input your own scopes"), paste:
   `https://www.googleapis.com/auth/youtube.upload`
4. Tap **Authorize APIs**.
5. Sign in with the Google account that owns **your YouTube channel**. If it asks which channel, choose yours.
6. If you see "Google hasn't verified this app", tap **Advanced → Go to Shorts Bot**. This is your own app, so it's safe.
7. Tap **Exchange authorization code for tokens**.
8. Copy the **Refresh token**.

### 5. Add the secrets to GitHub
1. In your repo, go to **Settings → Secrets and variables → Actions → New repository secret**.
2. Add these 4 secrets:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | key from step 1 |
| `YT_CLIENT_ID` | Client ID from step 3 |
| `YT_CLIENT_SECRET` | Client secret from step 3 |
| `YT_REFRESH_TOKEN` | refresh token from step 4 |

3. Then open the **Variables** tab and add `AUTO_PUBLISH` = `false` (see the warning below).

> ⚠️ **YouTube audit:** a new API project can only upload videos as **private**.
> - Videos will arrive in YouTube Studio as private drafts. Watch each one and tap **Publish**, which is a good habit anyway.
> - To let videos go public on schedule by themselves, submit the free **YouTube API Services audit form**: https://support.google.com/youtube/contact/yt_api_form. It takes a few days to a few weeks.
> - After you're approved, change `AUTO_PUBLISH` to `true`.

### 6. Test run
1. Open the **Actions** tab and choose **Daily Hindi Shorts → Run workflow**.
2. Set count = `1` and upload = `no`.
3. When it turns green (about 5–10 minutes), open the run. At the bottom, download the video and watch it.
4. If it looks good, run it again with upload = `yes`. After that it runs every night by itself.

### 7. Background music (optional)
Download a few no-copyright tracks from the **YouTube Audio Library** in YouTube Studio. Upload the `.mp3` files to `assets/music/` in the repo.

---

## Settings you can change later (GitHub Variables)

| Variable | What it does | Default |
|---|---|---|
| `POST_TIMES_IST` | posting times | `09:00,12:30,16:00,19:00,21:30` |
| `VOICE` | `hi-IN-MadhurNeural` (male) or `hi-IN-SwaraNeural` (female) | male |
| `NICHE` | what topics to cover | science, body, history |
| `AI_CLIPS_PER_VIDEO` | real AI video scenes (paid, needs `REPLICATE_API_TOKEN`) | `0` (free) |

## Rules that keep the channel safe
- **Make the content original.** Don't re-upload or translate another creator's videos. This bot writes new scripts and uses its own mascot.
- **Watch a few videos every week.** YouTube demonetizes "mass-produced, repetitive" AI content, so check that the facts are right and the videos feel varied.
- **Keep the AI disclosure on.** The bot sets YouTube's synthetic-media flag on every upload.
- **YouTube's free API quota allows about 6 uploads a day.** Don't go above 6.

## Upgrade later
Once the channel earns, you can turn on real AI video clips. Add a Replicate token and set `AI_CLIPS_PER_VIDEO` (for example `1` for just the hook scene). You can also ask Claude to set up a rented GPU, which costs about ₹2,000–4,000 a month.
