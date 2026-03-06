from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .schemas import (
    ManualVideoRequest,
    VideoRequest,
    VideoResponse,
    YouTubeAuthStartResponse,
    YouTubeAuthStatus,
    YouTubePublishRequest,
    YouTubePublishResponse,
)
from .services import image_service, script_service, tts_service, video_service, youtube_service

app = FastAPI(title="SacredClips API")

# CORS so frontend (Vite dev server) can call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Media root (for serving outputs/* as /media/...)
media_root = Path(config.BASE_OUTPUT_DIR).resolve()
media_root.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_root)), name="media")


@app.get("/health")
def health():
    return {"status": "ok"}


def _slugify(text: str) -> str:
    return (
        text.lower()
        .replace("?", "")
        .replace("!", "")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
    )[:80]


def _prepare_topic_dirs(topic: str) -> tuple[Path, Path, Path, Path]:
    topic_slug = _slugify(topic)
    topic_dir = media_root / topic_slug
    audio_dir = topic_dir / "audio"
    images_dir = topic_dir / "images"
    videos_dir = topic_dir / "videos"

    audio_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)

    return topic_dir, audio_dir, images_dir, videos_dir


@app.post("/generate-video", response_model=VideoResponse)
def generate_video(req: VideoRequest):
    # Clamp requested duration into [60, 90] for stricter control
    target_duration = max(60.0, min(float(req.duration_seconds), 90.0))

    _, audio_dir, images_dir, videos_dir = _prepare_topic_dirs(req.topic)

    # 1) Script + scenes (AI or fallback)
    req_for_script = VideoRequest(
        topic=req.topic,
        style=req.style,
        platform=req.platform,
        duration_seconds=target_duration,
    )
    script_text, scenes, used_ai = script_service.generate_script(req_for_script)

    # 2) Generate images (one per scene)
    per_scene_keywords = [s.keywords for s in scenes]
    image_paths = image_service.generate_images_for_keywords(
        topic=req.topic,
        per_scene_keywords=per_scene_keywords,
        output_dir=str(images_dir),
    )

    # 3) TTS audio from script_text
    audio_path = tts_service.text_to_speech(
        text=script_text,
        output_dir=str(audio_dir),
        filename="voiceover.mp3",
    )

    # 4) Render video – video_service enforces [60, 90] seconds
    scene_durations = [s.duration_seconds for s in scenes]
    video_path = video_service.render_video(
        image_paths=image_paths,
        audio_path=audio_path,
        scene_durations=scene_durations,
        output_dir=str(videos_dir),
        filename="final_video.mp4",
    )

    abs_video_path = Path(video_path).resolve()
    rel_to_media = abs_video_path.relative_to(media_root)
    video_url = f"/media/{rel_to_media.as_posix()}"

    return VideoResponse(
        video_path=str(abs_video_path),
        video_url=video_url,
        script_text=script_text,
        scenes=scenes,
        used_ai=used_ai,
    )


@app.post("/generate-video-from-script", response_model=VideoResponse)
def generate_video_from_script(req: ManualVideoRequest):
    """
    Regenerate a video from an edited script.

    We:
    - Use the edited script_text for TTS.
    - Reuse the scenes (durations & keywords) provided by the frontend.
    - Regenerate images + video.
    """
    _, audio_dir, images_dir, videos_dir = _prepare_topic_dirs(req.topic)

    scenes = req.scenes

    # 1) Images from keywords
    per_scene_keywords = [s.keywords for s in scenes]
    image_paths = image_service.generate_images_for_keywords(
        topic=req.topic,
        per_scene_keywords=per_scene_keywords,
        output_dir=str(images_dir),
    )

    # 2) TTS from edited script_text
    audio_path = tts_service.text_to_speech(
        text=req.script_text,
        output_dir=str(audio_dir),
        filename="voiceover.mp3",
    )

    # 3) Video rendering – enforce [60, 90] seconds inside video_service
    scene_durations = [s.duration_seconds for s in scenes]
    video_path = video_service.render_video(
        image_paths=image_paths,
        audio_path=audio_path,
        scene_durations=scene_durations,
        output_dir=str(videos_dir),
        filename="final_video.mp4",
    )

    abs_video_path = Path(video_path).resolve()
    rel_to_media = abs_video_path.relative_to(media_root)
    video_url = f"/media/{rel_to_media.as_posix()}"

    # We mark used_ai=False because this script is now manual/edited
    return VideoResponse(
        video_path=str(abs_video_path),
        video_url=video_url,
        script_text=req.script_text,
        scenes=scenes,
        used_ai=False,
    )


@app.get("/auth/youtube/start", response_model=YouTubeAuthStartResponse)
def youtube_auth_start():
    """
    Start the YouTube OAuth flow.
    Returns the Google authorization URL for the frontend to redirect the user to.
    """
    if not youtube_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="YouTube OAuth is not configured on the server.",
        )

    auth_url = youtube_service.create_auth_url()
    return YouTubeAuthStartResponse(auth_url=auth_url)


@app.get("/auth/youtube/callback", response_class=HTMLResponse)
def youtube_auth_callback(
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
):
    """
    OAuth2 callback endpoint for Google / YouTube.
    Exchanges the authorization code for tokens and stores them locally.
    """
    if error:
        return HTMLResponse(
            f"<html><body><h3>Authorization failed</h3><p>{error}</p></body></html>",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not youtube_service.verify_state(state):
        return HTMLResponse(
            "<html><body><h3>Invalid or missing authorization state.</h3></body></html>",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not code:
        return HTMLResponse(
            "<html><body><h3>Missing authorization code.</h3></body></html>",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        youtube_service.exchange_code_for_tokens(code)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(
            "<html><body><h3>Could not complete YouTube authorization.</h3>"
            f"<p>{exc}</p></body></html>",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Simple HTML letting the user close the tab and return to the app.
    return HTMLResponse(
        """
        <html>
          <body>
            <h3>YouTube authorization successful.</h3>
            <p>You can close this tab and return to SacredClips.</p>
            <script>
              try {
                if (window.opener && window.opener.postMessage) {
                  window.opener.postMessage(
                    { source: 'sacredclips', type: 'youtube-auth-complete' },
                    '*'
                  );
                }
              } catch (e) {
                // ignore
              }
              // Try to close the window if it was opened as a popup
              window.close();
            </script>
          </body>
        </html>
        """
    )


@app.get("/auth/youtube/status", response_model=YouTubeAuthStatus)
def youtube_auth_status():
    """
    Lightweight endpoint so the frontend can know if YouTube is connected
    with valid, usable credentials.
    """
    connected = youtube_service.credentials_valid()
    return YouTubeAuthStatus(connected=connected)


@app.post("/publish/youtube", response_model=YouTubePublishResponse)
def publish_youtube(req: YouTubePublishRequest):
    """
    Upload a generated MP4 video to YouTube.
    """
    try:
        video_id, url = youtube_service.upload_video(
            video_path=req.video_path,
            title=req.title,
            description=req.description,
            privacy_status=req.privacy_status,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except youtube_service.YouTubeNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except youtube_service.YouTubeNotAuthorized as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload video to YouTube: {exc}",
        ) from exc

    return YouTubePublishResponse(
        youtube_video_id=video_id,
        youtube_url=url,
    )