import json
from pathlib import Path
from typing import Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .. import config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubeNotConfigured(Exception):
    pass


class YouTubeNotAuthorized(Exception):
    pass


def _token_path() -> Path:
    return Path(config.YOUTUBE_TOKEN_PATH).resolve()


def _auth_state_path() -> Path:
    """
    File-based storage for the most recent OAuth state + PKCE code_verifier.
    Good enough for local single-user development.
    """
    return Path(config.BASE_OUTPUT_DIR).resolve() / "youtube_oauth_state.json"


def is_configured() -> bool:
    return bool(
        config.GOOGLE_CLIENT_ID
        and config.GOOGLE_CLIENT_SECRET
        and config.GOOGLE_REDIRECT_URI
    )


def _client_config() -> dict:
    if not is_configured():
        raise YouTubeNotConfigured(
            "YouTube OAuth is not configured. "
            "Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI."
        )

    return {
        "web": {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "redirect_uris": [config.GOOGLE_REDIRECT_URI],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _build_flow() -> Flow:
    cfg = _client_config()
    flow = Flow.from_client_config(cfg, scopes=SCOPES)
    flow.redirect_uri = config.GOOGLE_REDIRECT_URI
    return flow


def _save_auth_state(state: str, code_verifier: str | None) -> None:
    path = _auth_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "state": state,
                "code_verifier": code_verifier,
            },
            f,
        )


def _load_auth_state() -> dict | None:
    path = _auth_state_path()
    if not path.exists():
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def clear_auth_state() -> None:
    path = _auth_state_path()
    try:
        path.unlink()
    except OSError:
        pass


def verify_state(state: str | None) -> bool:
    """
    Verify the returned state parameter against the stored value.
    Keep the auth-state file for the token exchange step; only clear it
    after a successful token exchange.
    """
    if not state:
        return False

    data = _load_auth_state()
    if not data:
        return False

    expected = data.get("state")
    return bool(expected and expected == state)


def create_auth_url() -> str:
    """
    Create the Google OAuth URL for YouTube upload scope.
    Save both the returned state and the PKCE code_verifier.
    """
    flow = _build_flow()
    flow.autogenerate_code_verifier = True

    auth_url, returned_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    _save_auth_state(returned_state, flow.code_verifier)
    return auth_url


def _save_credentials(creds: Credentials) -> None:
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)


def _load_credentials() -> Credentials | None:
    path = _token_path()
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=data.get("client_id") or config.GOOGLE_CLIENT_ID,
        client_secret=data.get("client_secret") or config.GOOGLE_CLIENT_SECRET,
        scopes=data.get("scopes") or SCOPES,
    )


def has_credentials() -> bool:
    """
    Returns True if we have stored OAuth credentials on disk.
    """
    return _token_path().exists()


def credentials_valid() -> bool:
    """
    Returns True if YouTube is configured and stored credentials are usable.
    """
    try:
        _ = _get_authorized_youtube_client()
        return True
    except Exception:  # noqa: BLE001
        return False


def exchange_code_for_tokens(code: str) -> None:
    """
    Exchange an authorization code for access/refresh tokens and persist them.
    Reuses the stored PKCE code_verifier from the auth-start step.
    """
    auth_state = _load_auth_state()
    if not auth_state:
        raise YouTubeNotAuthorized(
            "Missing stored OAuth state. Start the YouTube connection flow again."
        )

    code_verifier = auth_state.get("code_verifier")

    flow = _build_flow()
    if code_verifier:
        flow.code_verifier = code_verifier

    flow.fetch_token(code=code)
    creds = flow.credentials
    if not creds:
        raise YouTubeNotAuthorized("Failed to obtain credentials from Google.")

    _save_credentials(creds)
    clear_auth_state()


def _get_authorized_youtube_client():
    """
    Return an authorized YouTube Data API client or raise if not connected.
    """
    if not is_configured():
        raise YouTubeNotConfigured(
            "YouTube OAuth is not configured on the server."
        )

    creds = _load_credentials()
    if not creds:
        raise YouTubeNotAuthorized(
            "No stored YouTube credentials. Connect your YouTube account first."
        )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_credentials(creds)
        else:
            raise YouTubeNotAuthorized(
                "Stored YouTube credentials are invalid or expired."
            )

    return build("youtube", "v3", credentials=creds)


def upload_video(
    video_path: str,
    title: str,
    description: str,
    privacy_status: str | None = None,
) -> Tuple[str, str]:
    """
    Upload a video file to YouTube and return (video_id, url).
    Video must live under BASE_OUTPUT_DIR.
    """
    base_root = Path(config.BASE_OUTPUT_DIR).resolve()
    path = Path(video_path).expanduser().resolve()

    try:
        path.relative_to(base_root)
    except ValueError as exc:
        raise PermissionError(
            "Video path must be inside the configured output directory."
        ) from exc

    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {path}")

    privacy = (privacy_status or config.YOUTUBE_UPLOAD_DEFAULT_PRIVACY).lower()
    if privacy not in {"private", "unlisted", "public"}:
        privacy = config.YOUTUBE_UPLOAD_DEFAULT_PRIVACY

    youtube = _get_authorized_youtube_client()

    body = {
        "snippet": {
            "title": title,
            "description": description,
        },
        "status": {
            "privacyStatus": privacy,
        },
    }

    media = MediaFileUpload(
        str(path),
        mimetype="video/mp4",
        chunksize=-1,
        resumable=True,
    )

    try:
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            _, response = request.next_chunk()

        video_id = response.get("id")
        if not video_id:
            raise RuntimeError("YouTube API did not return a video ID.")

        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        return video_id, youtube_url
    except HttpError as exc:
        raise RuntimeError(f"YouTube API error: {exc}") from exc