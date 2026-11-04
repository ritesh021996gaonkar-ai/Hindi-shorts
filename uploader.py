"""Uploads a finished short to YouTube (Data API v3)."""
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _client():
    creds = Credentials(
        None,
        refresh_token=config.YT_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.YT_CLIENT_ID,
        client_secret=config.YT_CLIENT_SECRET,
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(path, title, description, tags, publish_at_utc=None, shorts=True):
    """publish_at_utc: 'YYYY-MM-DDTHH:MM:SSZ' to schedule, or None for a private draft."""
    status = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": True,   # honest AI disclosure, required by YouTube
    }
    if publish_at_utc:
        status["publishAt"] = publish_at_utc
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags[:15],
            "categoryId": "27",            # Education (both shorts and long videos)
            "defaultLanguage": "hi",
            "defaultAudioLanguage": "hi",
        },
        "status": status,
    }
    req = _client().videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(path), mimetype="video/mp4",
                                   chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


def set_thumbnail(video_id, image_path):
    """Custom thumbnail (needs a phone-verified YouTube channel)."""
    _client().thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(str(image_path), mimetype="image/jpeg")).execute()
