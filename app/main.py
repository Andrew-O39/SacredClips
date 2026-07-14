import asyncio
import json
from pathlib import Path
from typing import Any, Callable, List, Literal, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter, ValidationError

from . import config
from .schemas import (
    AspectRatio,
    BackgroundMusic,
    BrandingPosition,
    BrandingSize,
    BrandingUploadResponse,
    ImageFitMode,
    ManualVideoRequest,
    MotionEffect,
    MotionIntensity,
    PreviewSceneRequest,
    PreviewSceneResponse,
    RenderJobListResponse,
    RenderJobStartResponse,
    RenderJobStatus,
    RenderSubtitlesVideoResponse,
    Scene,
    SubtitleItem,
    SubtitleStyle,
    VideoRequest,
    VideoResponse,
    VisualStyle,
    YouTubeAuthStartResponse,
    YouTubeAuthStatus,
    YouTubePublishRequest,
    YouTubePublishResponse,
)
from .services import image_service, output_path_service, render_job_service, script_service, tts_service, video_service, youtube_service

ProgressFn = Callable[[str, float], None]


def _noop_progress(_stage: str, _pct: float) -> None:
    pass


app = FastAPI(title="SacredClips API")


@app.on_event("startup")
def _startup_render_jobs() -> None:
    render_job_service.init_render_jobs()

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

# Static royalty-free music previews and other bundled assets (served as /assets/...)
_assets_root = Path(__file__).resolve().parent.parent / "assets"
_assets_root.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=str(_assets_root)), name="assets")


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


_visual_style_adapter = TypeAdapter(VisualStyle)
_aspect_ratio_adapter = TypeAdapter(AspectRatio)
_image_fit_mode_adapter = TypeAdapter(ImageFitMode)
_background_music_adapter = TypeAdapter(BackgroundMusic)
_motion_effect_adapter = TypeAdapter(MotionEffect)
_motion_intensity_adapter = TypeAdapter(MotionIntensity)
_subtitle_style_adapter = TypeAdapter(SubtitleStyle)
_branding_position_adapter = TypeAdapter(BrandingPosition)
_branding_size_adapter = TypeAdapter(BrandingSize)

BRANDING_DIR = media_root / "branding"


def _normalize_visual_style(value: object) -> VisualStyle:
    try:
        return _visual_style_adapter.validate_python(value)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Invalid visual_style", "detail": exc.errors()},
        ) from exc


def _normalize_aspect_ratio(value: object) -> AspectRatio:
    try:
        return _aspect_ratio_adapter.validate_python(value)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Invalid aspect_ratio", "detail": exc.errors()},
        ) from exc


def _clamp_duration_by_aspect(duration_seconds: float, aspect_ratio: AspectRatio) -> float:
    if aspect_ratio == "9:16":
        lo, hi = 60.0, 90.0
    elif aspect_ratio == "1:1":
        lo, hi = 60.0, 180.0
    else:
        lo, hi = 120.0, 600.0
    return max(lo, min(float(duration_seconds), hi))


def _normalize_image_fit_mode(value: object) -> ImageFitMode:
    try:
        return _image_fit_mode_adapter.validate_python(value)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Invalid image_fit_mode", "detail": exc.errors()},
        ) from exc


def _normalize_background_music(value: object) -> BackgroundMusic:
    try:
        return _background_music_adapter.validate_python(value)
    except ValidationError:
        return "none"


def _normalize_motion_effect(value: object) -> MotionEffect:
    try:
        return _motion_effect_adapter.validate_python(value)
    except ValidationError:
        return "gentle_zoom"


def _normalize_motion_intensity(value: object) -> MotionIntensity:
    try:
        return _motion_intensity_adapter.validate_python(value)
    except ValidationError:
        return "subtle"


def _normalize_subtitle_style(value: object) -> SubtitleStyle:
    try:
        return _subtitle_style_adapter.validate_python(value)
    except ValidationError:
        return "off"


def _clamp_background_music_volume(raw: object) -> float:
    if raw is None or raw == "":
        return 0.12
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.12
    return max(0.0, min(0.5, v))


def _branding_dir() -> Path:
    BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    return BRANDING_DIR.resolve()


def _resolve_branding_logo_path(candidate: str | None) -> Path | None:
    return _safe_resolved_file_under_dir(_branding_dir(), candidate)


def _parse_bool_form(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _normalize_branding_position(value: object) -> BrandingPosition:
    try:
        return _branding_position_adapter.validate_python(value)
    except ValidationError:
        return "bottom_right"


def _normalize_branding_size(value: object) -> BrandingSize:
    try:
        return _branding_size_adapter.validate_python(value)
    except ValidationError:
        return "medium"


def _clamp_branding_opacity(raw: object) -> float:
    if raw is None or raw == "":
        return 0.8
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.8
    return max(0.0, min(1.0, v))


def _branding_render_kwargs(
    enabled: bool,
    logo_path: str | None,
    position: BrandingPosition,
    size: BrandingSize,
    opacity: float,
) -> dict:
    resolved = _resolve_branding_logo_path(logo_path) if enabled and logo_path else None
    use = bool(enabled and resolved)
    return {
        "branding_enabled": use,
        "branding_logo_path": str(resolved) if use and resolved else None,
        "branding_position": position,
        "branding_size": size,
        "branding_opacity": _clamp_branding_opacity(opacity),
    }


def _parse_branding_from_form(form) -> dict:
    path_raw = form.get("branding_logo_path")
    path = path_raw.strip() if isinstance(path_raw, str) and path_raw.strip() else None
    return _branding_render_kwargs(
        _parse_bool_form(form.get("branding_enabled")),
        path,
        _normalize_branding_position(form.get("branding_position")),
        _normalize_branding_size(form.get("branding_size")),
        _clamp_branding_opacity(form.get("branding_opacity")),
    )


def _parse_branding_from_dict(body: dict) -> dict:
    path_raw = body.get("branding_logo_path")
    path = path_raw if isinstance(path_raw, str) and path_raw.strip() else None
    return _branding_render_kwargs(
        bool(body.get("branding_enabled")),
        path,
        _normalize_branding_position(body.get("branding_position")),
        _normalize_branding_size(body.get("branding_size")),
        _clamp_branding_opacity(body.get("branding_opacity")),
    )


def _sort_scenes(scenes: List[Scene]) -> List[Scene]:
    """Stable order for pipeline: ascending scene.index."""
    return sorted(scenes, key=lambda s: s.index)


def _strip_scene_for_render(s: Scene) -> Scene:
    """Forget client-side image URL; keep persisted manual asset hints for regeneration."""
    return Scene(
        index=s.index,
        text=s.text,
        keywords=s.keywords,
        duration_seconds=s.duration_seconds,
        image_mode=s.image_mode,
        image_path=s.image_path,
    )


def _media_url_to_local_path(url: str | None) -> Path | None:
    """Map a /media/... URL from our API to an absolute path under media_root, if the file exists."""
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if not u.startswith("/media/"):
        return None
    rel = u[len("/media/") :].lstrip("/")
    try:
        p = (media_root / rel).resolve()
        p.relative_to(media_root.resolve())
        if p.is_file() and p.stat().st_size > 0:
            return p
    except Exception:
        return None
    return None


async def _parse_preview_scene_request(request: Request) -> tuple[PreviewSceneRequest, Any, Any]:
    """JSON body, or multipart with `payload` plus optional `preview_image` and `audio_upload` files."""
    ct = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in ct:
        form = await request.form()
        raw = form.get("payload")
        if not isinstance(raw, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="multipart preview requires form field 'payload' (JSON string)",
            )
        try:
            data = PreviewSceneRequest.model_validate_json(raw)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.errors(),
            ) from exc
        up = form.get("preview_image")
        image_upload = up if up is not None and hasattr(up, "read") else None
        audio_up = form.get("audio_upload")
        audio_upload = audio_up if audio_up is not None and hasattr(audio_up, "read") else None
        return data, image_upload, audio_upload
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body",
        ) from exc
    try:
        data = PreviewSceneRequest.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    return data, None, None


def _path_to_media_url(abs_img: Path) -> str:
    rel = abs_img.resolve().relative_to(media_root)
    return f"/media/{rel.as_posix()}"


def _safe_resolved_file_under_dir(expected_parent: Path, candidate: str | None) -> Path | None:
    """Reject path traversal: only files under expected_parent (resolved) are accepted."""
    if not candidate or not isinstance(candidate, str):
        return None
    try:
        raw = Path(candidate).expanduser()
        if raw.is_absolute():
            resolved = raw.resolve()
        else:
            resolved = output_path_service.from_output_relative(candidate)
        parent = expected_parent.resolve()
        resolved.relative_to(parent)
        if resolved.is_file() and resolved.stat().st_size > 0:
            return resolved
    except Exception:
        return None
    return None


def _scenes_with_image_urls(scenes_ordered: List[Scene], image_paths: List[str]) -> List[Scene]:
    combined: List[Scene] = []
    for idx, scene in enumerate(scenes_ordered):
        img_url: str | None = None
        ip = scene.image_path
        if idx < len(image_paths):
            abs_img = Path(image_paths[idx]).resolve()
            img_url = _path_to_media_url(abs_img)
            ip = str(abs_img)
        combined.append(scene.model_copy(update={"image_url": img_url, "image_path": ip}))
    return combined


def _finalize_video_response(
    *,
    topic: str,
    script_text: str,
    scenes_ordered: List[Scene],
    image_paths: List[str],
    audio_path: str,
    videos_dir: Path,
    used_ai_flag: bool,
    aspect_ratio: AspectRatio,
    image_fit_mode: str = "fit",
    background_music: BackgroundMusic = "none",
    background_music_volume: float = 0.12,
    motion_effect: MotionEffect = "gentle_zoom",
    motion_intensity: MotionIntensity = "subtle",
    subtitle_style: SubtitleStyle = "off",
    narration_source: Optional[Literal["tts", "upload"]] = None,
    narration_audio_path: Optional[str] = None,
    branding_enabled: bool = False,
    branding_logo_path: Optional[str] = None,
    branding_position: BrandingPosition = "bottom_right",
    branding_size: BrandingSize = "medium",
    branding_opacity: float = 0.8,
) -> VideoResponse:
    scene_durations = [s.duration_seconds for s in scenes_ordered]
    subtitle_texts = [s.text for s in scenes_ordered]
    while len(subtitle_texts) < len(image_paths):
        subtitle_texts.append("")
    subtitle_texts = subtitle_texts[: len(image_paths)]
    video_path = video_service.render_video(
        image_paths=image_paths,
        audio_path=audio_path,
        scene_durations=scene_durations,
        output_dir=str(videos_dir),
        filename="final_video.mp4",
        aspect_ratio=aspect_ratio,
        image_fit_mode=image_fit_mode,
        background_music=background_music,
        background_music_volume=background_music_volume,
        motion_effect=motion_effect,
        motion_intensity=motion_intensity,
        subtitle_style=subtitle_style,
        subtitle_texts=subtitle_texts,
        branding_enabled=branding_enabled,
        branding_logo_path=branding_logo_path,
        branding_position=str(branding_position),
        branding_size=str(branding_size),
        branding_opacity=branding_opacity,
    )
    abs_video_path = Path(video_path).resolve()
    rel_to_media = abs_video_path.relative_to(media_root)
    video_url = f"/media/{rel_to_media.as_posix()}"
    scenes_out = _scenes_with_image_urls(scenes_ordered, image_paths)
    return VideoResponse(
        video_path=str(abs_video_path),
        video_url=video_url,
        script_text=script_text,
        scenes=scenes_out,
        used_ai=used_ai_flag,
        narration_source=narration_source,
        narration_audio_path=narration_audio_path,
    )


def _regenerate_from_manual_request(
    req: ManualVideoRequest,
    progress: ProgressFn = _noop_progress,
) -> VideoResponse:
    """
    Images + TTS + render from structured scenes & script_text (edited script / scenes).

    Reuses uploaded scene images and uploaded narration paths when the client resends them.
    """
    progress("preparing", 8)
    _, audio_dir, images_dir, videos_dir = _prepare_topic_dirs(req.topic)
    scenes_sorted = [_strip_scene_for_render(s) for s in _sort_scenes(req.scenes)]
    image_paths: List[str] = []
    scenes_for_finalize: List[Scene] = []
    n_scenes = max(len(scenes_sorted), 1)

    for i, s in enumerate(scenes_sorted):
        base_path = images_dir / f"scene_{s.index}_manual"
        mode = s.image_mode

        if mode == "upload" and s.image_path:
            safe = _safe_resolved_file_under_dir(images_dir, s.image_path)
            if safe:
                rp = str(safe)
                image_paths.append(rp)
                scenes_for_finalize.append(s.model_copy(update={"image_path": rp, "image_mode": "upload"}))
                continue

        if mode == "placeholder":
            dest = Path(f"{base_path}_placeholder.png")
            image_service.write_placeholder_scene_image(
                topic=req.topic,
                keywords=s.keywords,
                scene_index=s.index,
                visual_style=req.visual_style,
                aspect_ratio=req.aspect_ratio,
                output_path=str(dest),
                scene_text=s.text,
            )
            rp = str(dest.resolve())
            image_paths.append(rp)
            scenes_for_finalize.append(s.model_copy(update={"image_path": rp, "image_mode": "placeholder"}))
            continue

        # generate (explicit) or unknown / missing upload path — regenerate AI image
        ai_scene_dir = images_dir / f"scene_{s.index}_manual_ai_regen"
        generated = image_service.generate_images_for_keywords(
            topic=req.topic,
            per_scene_keywords=[s.keywords],
            output_dir=str(ai_scene_dir),
            visual_style=req.visual_style,
            aspect_ratio=req.aspect_ratio,
            scene_texts=[s.text],
        )
        if generated:
            p = Path(generated[0]).resolve()
            rp = str(p)
            image_paths.append(rp)
            scenes_for_finalize.append(s.model_copy(update={"image_path": rp, "image_mode": "generate"}))
        else:
            dest = Path(f"{base_path}_placeholder.png")
            image_service.write_placeholder_scene_image(
                topic=req.topic,
                keywords=s.keywords,
                scene_index=s.index,
                visual_style=req.visual_style,
                aspect_ratio=req.aspect_ratio,
                output_path=str(dest),
                scene_text=s.text,
            )
            rp = str(dest.resolve())
            image_paths.append(rp)
            scenes_for_finalize.append(s.model_copy(update={"image_path": rp, "image_mode": "placeholder"}))

        progress("images", 15 + (55 * (i + 1) / n_scenes))

    progress("narration", 72)
    narr_source: Literal["tts", "upload"] = "tts"
    narr_path_out: Optional[str] = None
    if req.narration_source == "upload" and req.narration_audio_path:
        audio_ok = _safe_resolved_file_under_dir(audio_dir, req.narration_audio_path)
        if audio_ok:
            audio_path = str(audio_ok)
            narr_source = "upload"
            narr_path_out = audio_path
        else:
            audio_path = tts_service.text_to_speech(
                text=req.script_text,
                output_dir=str(audio_dir),
                filename="voiceover.mp3",
            )
    else:
        audio_path = tts_service.text_to_speech(
            text=req.script_text,
            output_dir=str(audio_dir),
            filename="voiceover.mp3",
        )

    progress("rendering", 85)
    return _finalize_video_response(
        topic=req.topic,
        script_text=req.script_text,
        scenes_ordered=scenes_for_finalize,
        image_paths=image_paths,
        audio_path=audio_path,
        videos_dir=videos_dir,
        used_ai_flag=False,
        aspect_ratio=req.aspect_ratio,
        image_fit_mode=req.image_fit_mode,
        background_music=req.background_music,
        background_music_volume=req.background_music_volume,
        motion_effect=req.motion_effect,
        motion_intensity=req.motion_intensity,
        subtitle_style=req.subtitle_style,
        narration_source=narr_source,
        narration_audio_path=narr_path_out,
        **_branding_render_kwargs(
            req.branding_enabled,
            req.branding_logo_path,
            req.branding_position,
            req.branding_size,
            req.branding_opacity,
        ),
    )


@app.post("/generate-video", response_model=VideoResponse)
def generate_video(req: VideoRequest):
    return _execute_generate_video(req)


def _execute_generate_video(req: VideoRequest, progress: ProgressFn = _noop_progress) -> VideoResponse:
    progress("preparing", 5)
    target_duration = _clamp_duration_by_aspect(req.duration_seconds, req.aspect_ratio)

    _, audio_dir, images_dir, videos_dir = _prepare_topic_dirs(req.topic)

    progress("script", 15)
    req_for_script = VideoRequest(
        topic=req.topic,
        style=req.style,
        duration_seconds=target_duration,
        visual_style=req.visual_style,
        aspect_ratio=req.aspect_ratio,
        image_fit_mode=req.image_fit_mode,
        background_music=req.background_music,
        background_music_volume=req.background_music_volume,
        motion_effect=req.motion_effect,
        motion_intensity=req.motion_intensity,
        subtitle_style=req.subtitle_style,
    )
    script_text, scenes_raw, used_ai = script_service.generate_script(req_for_script)
    scenes_ordered = [_strip_scene_for_render(s) for s in _sort_scenes(scenes_raw)]

    progress("images", 35)
    per_scene_keywords = [s.keywords for s in scenes_ordered]
    scene_texts = [s.text for s in scenes_ordered]
    image_paths = image_service.generate_images_for_keywords(
        topic=req.topic,
        per_scene_keywords=per_scene_keywords,
        output_dir=str(images_dir),
        visual_style=req.visual_style,
        aspect_ratio=req.aspect_ratio,
        scene_texts=scene_texts,
    )

    progress("narration", 65)
    audio_path = tts_service.text_to_speech(
        text=script_text,
        output_dir=str(audio_dir),
        filename="voiceover.mp3",
    )

    progress("rendering", 85)
    branding = _branding_render_kwargs(
        req.branding_enabled,
        req.branding_logo_path,
        req.branding_position,
        req.branding_size,
        req.branding_opacity,
    )

    progress("finalizing", 95)
    return _finalize_video_response(
        topic=req.topic,
        script_text=script_text,
        scenes_ordered=scenes_ordered,
        image_paths=image_paths,
        audio_path=audio_path,
        videos_dir=videos_dir,
        used_ai_flag=used_ai,
        aspect_ratio=req.aspect_ratio,
        image_fit_mode=req.image_fit_mode,
        background_music=req.background_music,
        background_music_volume=req.background_music_volume,
        motion_effect=req.motion_effect,
        motion_intensity=req.motion_intensity,
        subtitle_style=req.subtitle_style,
        narration_source="tts",
        narration_audio_path=None,
        **branding,
    )


def _job_record_to_status(rec: dict[str, Any]) -> RenderJobStatus:
    return RenderJobStatus.model_validate(rec)


def _run_async_in_thread(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _SnapshotUpload:
    def __init__(self, data: bytes, filename: str) -> None:
        self._data = data
        self.filename = filename

    async def read(self) -> bytes:
        return self._data


class _SnapshotForm:
    """Thread-safe replay of multipart form fields for background render jobs."""

    def __init__(
        self,
        fields: dict[str, str],
        single_files: dict[str, _SnapshotUpload],
        list_files: dict[str, list[_SnapshotUpload]],
    ) -> None:
        self._fields = fields
        self._single_files = single_files
        self._list_files = list_files

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._single_files:
            return self._single_files[key]
        if key in self._list_files and self._list_files[key]:
            return self._list_files[key][0]
        return self._fields.get(key, default)

    def getlist(self, key: str) -> list[Any]:
        if key in self._list_files:
            return self._list_files[key]
        if key in self._single_files:
            return [self._single_files[key]]
        val = self._fields.get(key)
        return [val] if val is not None else []

    def keys(self) -> list[str]:
        keys = set(self._fields.keys()) | set(self._single_files.keys()) | set(self._list_files.keys())
        return list(keys)


async def _snapshot_multipart_form(form: Any) -> _SnapshotForm:
    fields: dict[str, str] = {}
    single_files: dict[str, _SnapshotUpload] = {}
    list_files: dict[str, list[_SnapshotUpload]] = {}
    for key in form.keys():
        vals = form.getlist(key)
        uploads: list[_SnapshotUpload] = []
        for val in vals:
            if hasattr(val, "read"):
                raw = await val.read()
                filename = getattr(val, "filename", None) or "file"
                uploads.append(_SnapshotUpload(raw or b"", str(filename)))
            else:
                fields[key] = str(val)
        if uploads:
            if len(uploads) == 1:
                single_files[key] = uploads[0]
            list_files[key] = uploads
    return _SnapshotForm(fields, single_files, list_files)


def _execute_render_subtitles(
    *,
    source_video: Path,
    out_mp4: Path,
    subtitle_items: List[SubtitleItem],
    subtitle_style: SubtitleStyle,
    branding: dict[str, Any],
    progress: ProgressFn = _noop_progress,
) -> RenderSubtitlesVideoResponse:
    progress("rendering", 55)
    video_service.render_subtitles_on_video(
        video_path=str(source_video),
        output_path=str(out_mp4),
        subtitles=[s.model_dump() for s in subtitle_items],
        subtitle_style=str(subtitle_style),
        **branding,
    )
    progress("finalizing", 95)
    abs_out = out_mp4.resolve()
    return RenderSubtitlesVideoResponse(
        video_path=str(abs_out),
        video_url=_path_to_media_url(abs_out),
        source_video_path=str(source_video.resolve()),
        source_video_url=_path_to_media_url(source_video.resolve()),
    )


async def _prepare_subtitles_render(request: Request) -> tuple[
    SubtitleStyle,
    List[SubtitleItem],
    Path,
    Path,
    dict[str, Any],
]:
    ct = (request.headers.get("content-type") or "").lower()
    subtitle_style_raw: object
    subtitles_raw: object
    source_video: Path | None = None
    branding: dict[str, Any]

    if "multipart/form-data" in ct:
        form = await request.form()
        topic_val = form.get("topic")
        if not isinstance(topic_val, str) or not topic_val.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="topic is required")
        topic = topic_val.strip()
        topic_dir, _, _, _ = _prepare_topic_dirs(topic)
        uploads_dir = topic_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        subtitle_style_raw = form.get("subtitle_style") or "minimal"
        subtitles_raw = form.get("subtitles_json")
        upload = form.get("video_upload")
        if upload is not None and hasattr(upload, "read"):
            filename = getattr(upload, "filename", None) or "uploaded_video.mp4"
            suffix = Path(str(filename)).suffix.lower()
            if suffix not in {".mp4", ".mov", ".mkv", ".webm"}:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="video_upload must be .mp4, .mov, .mkv, or .webm",
                )
            dest = uploads_dir / f"existing_video_upload{suffix}"
            try:
                raw = await upload.read()
            except Exception as read_exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Could not read video_upload: {read_exc}",
                ) from read_exc
            if raw:
                dest.write_bytes(raw)
                source_video = dest.resolve()
        else:
            path_val = form.get("source_video_path") or form.get("video_path")
            if isinstance(path_val, str):
                source_video = _safe_resolved_file_under_dir(uploads_dir, path_val)

        branding = _parse_branding_from_form(form)
        logo_up = form.get("branding_logo_upload")
        if logo_up is not None and hasattr(logo_up, "read"):
            saved_logo = await _save_branding_logo_upload(logo_up)
            if saved_logo:
                branding = _branding_render_kwargs(
                    _parse_bool_form(form.get("branding_enabled")),
                    str(saved_logo),
                    _normalize_branding_position(form.get("branding_position")),
                    _normalize_branding_size(form.get("branding_size")),
                    _clamp_branding_opacity(form.get("branding_opacity")),
                )
    else:
        body = await request.json()
        topic_val = body.get("topic")
        if not isinstance(topic_val, str) or not topic_val.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="topic is required")
        topic = topic_val.strip()
        topic_dir, _, _, _ = _prepare_topic_dirs(topic)
        uploads_dir = topic_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        subtitle_style_raw = body.get("subtitle_style") or "minimal"
        subtitles_raw = body.get("subtitles") or body.get("subtitles_json")
        path_val = body.get("source_video_path") or body.get("video_path")
        source_video = _safe_resolved_file_under_dir(uploads_dir, path_val if isinstance(path_val, str) else None)
        branding = _parse_branding_from_dict(body)

    if source_video is None or not source_video.is_file() or source_video.stat().st_size <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A valid uploaded video is required")

    subtitle_style = _normalize_subtitle_style(subtitle_style_raw)
    if isinstance(subtitles_raw, str):
        try:
            subtitle_items = TypeAdapter(List[SubtitleItem]).validate_json(subtitles_raw)
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
    else:
        try:
            subtitle_items = TypeAdapter(List[SubtitleItem]).validate_python(subtitles_raw or [])
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc

    if subtitle_style != "off" and not subtitle_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one subtitle item, or choose subtitle style 'off'.",
        )

    topic_dir, _, _, _ = _prepare_topic_dirs(topic)
    rendered_dir = topic_dir / "rendered"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = rendered_dir / "subtitled_video.mp4"
    return subtitle_style, subtitle_items, source_video, out_mp4, branding


@app.post("/generate-video-from-script", response_model=VideoResponse)
def generate_video_from_script(req: ManualVideoRequest):
    """
    Regenerate a video from an edited script.

    We:
    - Use the edited script_text for TTS.
    - Reuse the scenes (durations & keywords) provided by the frontend.
    - Regenerate images + video.
    """
    return _regenerate_from_manual_request(req)


@app.post("/generate-video-from-scenes", response_model=VideoResponse)
def generate_video_from_scenes(req: ManualVideoRequest):
    """
    Same payload as /generate-video-from-script: rebuild from edited scene cards + script text.
    """
    return _regenerate_from_manual_request(req)


@app.post("/preview-scene", response_model=PreviewSceneResponse)
async def preview_scene(request: Request):
    """
    Render a single-scene MP4 for quick preview: image + motion + subtitles + narration slice + optional music.

    JSON body (`PreviewSceneRequest`), or multipart with form field `payload` (JSON string), optional
    `preview_image`, and optional `audio_upload` for manual pre-render previews.
    """
    data, upload, audio_upload = await _parse_preview_scene_request(request)
    topic_dir, audio_dir, images_dir, videos_dir = _prepare_topic_dirs(data.topic)
    previews_dir = topic_dir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)

    scenes_ordered = [_strip_scene_for_render(s) for s in _sort_scenes(data.scenes)]
    selected: Scene | None = None
    for s in scenes_ordered:
        if s.index == data.scene_index:
            selected = s
            break
    if selected is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scene_index not found in scenes")

    scene_start = 0.0
    for s in scenes_ordered:
        if s.index == data.scene_index:
            break
        scene_start += float(s.duration_seconds)

    scene_duration = max(float(video_service.MIN_SCENE_CLIP), float(selected.duration_seconds))

    img_path_res: Path | None = None
    if upload is not None:
        filename = getattr(upload, "filename", None) or "preview.png"
        suffix = Path(str(filename)).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            suffix = ".png"
        dest = previews_dir / f"scene_{data.scene_index}_preview_input{suffix}"
        try:
            raw = await upload.read()
        except Exception as read_exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not read preview_image: {read_exc}",
            ) from read_exc
        if raw:
            dest.write_bytes(raw)
            if dest.exists() and dest.stat().st_size > 0:
                img_path_res = dest.resolve()

    if img_path_res is None:
        safe_img = _safe_resolved_file_under_dir(images_dir, selected.image_path)
        if safe_img:
            img_path_res = safe_img

    if img_path_res is None and selected.image_url:
        url_path = _media_url_to_local_path(selected.image_url)
        if url_path:
            img_path_res = url_path

    if img_path_res is None and selected.image_mode == "generate":
        generated = image_service.generate_images_for_keywords(
            topic=data.topic,
            per_scene_keywords=[list(selected.keywords or ["scene"])],
            output_dir=str(previews_dir / f"scene_{data.scene_index}_generated_image"),
            visual_style=str(data.visual_style),
            aspect_ratio=str(data.aspect_ratio),
            scene_texts=[selected.text],
        )
        if generated:
            gen_path = Path(generated[0]).resolve()
            if gen_path.is_file() and gen_path.stat().st_size > 0:
                img_path_res = gen_path

    if img_path_res is None:
        ph = previews_dir / f"_preview_placeholder_scene_{data.scene_index}.png"
        image_service.write_placeholder_scene_image(
            topic=data.topic,
            keywords=list(selected.keywords or ["scene"]),
            scene_index=selected.index,
            visual_style=str(data.visual_style),
            aspect_ratio=str(data.aspect_ratio),
            output_path=str(ph),
            scene_text=selected.text,
        )
        img_path_res = ph.resolve()

    narr_path_obj: Path | None = None
    src_mode = (data.narration_source or "").strip().lower()
    if src_mode == "upload":
        if audio_upload is not None:
            filename = getattr(audio_upload, "filename", None) or "preview_audio.mp3"
            suffix = Path(str(filename)).suffix.lower()
            if suffix not in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".webm"}:
                suffix = ".mp3"
            audio_dest = previews_dir / f"scene_{data.scene_index}_preview_audio{suffix}"
            try:
                raw_audio = await audio_upload.read()
            except Exception as read_exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Could not read audio_upload: {read_exc}",
                ) from read_exc
            if raw_audio:
                audio_dest.write_bytes(raw_audio)
                if audio_dest.exists() and audio_dest.stat().st_size > 0:
                    narr_path_obj = audio_dest.resolve()

        if narr_path_obj is None and data.narration_audio_path:
            narr_path_obj = _safe_resolved_file_under_dir(audio_dir, data.narration_audio_path)
    elif src_mode == "tts" or not src_mode:
        vo = (audio_dir / "voiceover.mp3").resolve()
        try:
            vo.relative_to(audio_dir.resolve())
            if vo.is_file() and vo.stat().st_size > 0:
                narr_path_obj = vo
        except Exception:
            pass

    out_mp4 = previews_dir / f"scene_{data.scene_index}_preview.mp4"
    video_service.render_scene_preview(
        image_path=str(img_path_res),
        output_path=str(out_mp4),
        scene_duration=scene_duration,
        aspect_ratio=str(data.aspect_ratio),
        image_fit_mode=str(data.image_fit_mode),
        background_music=str(data.background_music),
        background_music_volume=float(data.background_music_volume),
        motion_effect=str(data.motion_effect),
        motion_intensity=str(data.motion_intensity),
        subtitle_style=str(data.subtitle_style),
        subtitle_text=selected.text,
        full_narration_path=str(narr_path_obj) if narr_path_obj else None,
        narration_start_sec=scene_start,
    )

    abs_out = out_mp4.resolve()
    return PreviewSceneResponse(
        preview_video_path=str(abs_out),
        preview_video_url=_path_to_media_url(abs_out),
    )


@app.post("/render-subtitles-video", response_model=RenderSubtitlesVideoResponse)
async def render_subtitles_video(request: Request):
    """
    Burn manually timed subtitles onto an uploaded/existing local video.

    Preferred multipart fields:
      - topic
      - subtitle_style
      - subtitles_json: JSON array of {id, start_seconds, end_seconds, text}
      - video_upload: mp4/mov/mkv/webm file

    Re-renders may omit `video_upload` and provide a safe `source_video_path` under the topic uploads folder.
    """
    subtitle_style, subtitle_items, source_video, out_mp4, branding = await _prepare_subtitles_render(request)
    return _execute_render_subtitles(
        source_video=source_video,
        out_mp4=out_mp4,
        subtitle_items=subtitle_items,
        subtitle_style=subtitle_style,
        branding=branding,
    )


async def _manual_video_from_form(form: Any, progress: ProgressFn = _noop_progress) -> VideoResponse:
    progress("preparing", 8)
    topic = form.get("topic")
    script_text = form.get("script_text")
    scenes_json = form.get("scenes_json")
    narration_source_raw = form.get("narration_source")
    narration_source = narration_source_raw.strip().lower() if isinstance(narration_source_raw, str) else "tts"
    if narration_source not in {"tts", "upload"}:
        raise HTTPException(status_code=400, detail="Invalid narration_source. Use 'tts' or 'upload'.")
    print(f"[manual-video] narration_source={narration_source}")
    if not isinstance(topic, str) or not topic.strip():
        raise HTTPException(status_code=400, detail="topic is required")
    if not isinstance(script_text, str):
        raise HTTPException(status_code=400, detail="script_text is required")
    if not isinstance(scenes_json, str):
        raise HTTPException(status_code=400, detail="scenes_json is required")

    try:
        raw_scenes = json.loads(scenes_json)
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise ValueError("scenes_json must be a non-empty array")
        scene_models: List[Scene] = []
        for item in raw_scenes:
            if isinstance(item, dict):
                item.pop("image_url", None)
            scene_models.append(Scene.model_validate(item))
    except (json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scenes_json: {exc}",
        ) from exc

    vs_raw = form.get("visual_style")
    if vs_raw is None or vs_raw == "":
        visual_style = _normalize_visual_style("Classical sacred art")
    else:
        visual_style = _normalize_visual_style(vs_raw)
    ar_raw = form.get("aspect_ratio")
    if ar_raw is None or ar_raw == "":
        aspect_ratio = _normalize_aspect_ratio("16:9")
    else:
        aspect_ratio = _normalize_aspect_ratio(ar_raw)
    ifm_raw = form.get("image_fit_mode")
    if ifm_raw is None or ifm_raw == "":
        image_fit_mode = _normalize_image_fit_mode("fill" if aspect_ratio == "9:16" else "fit")
    else:
        image_fit_mode = _normalize_image_fit_mode(ifm_raw)

    background_music = _normalize_background_music(form.get("background_music"))
    background_music_volume = _clamp_background_music_volume(form.get("background_music_volume"))
    motion_effect = _normalize_motion_effect(form.get("motion_effect"))
    motion_intensity = _normalize_motion_intensity(form.get("motion_intensity"))
    subtitle_style = _normalize_subtitle_style(form.get("subtitle_style"))

    _, audio_dir, images_dir, videos_dir = _prepare_topic_dirs(topic)
    scenes_ordered = [_strip_scene_for_render(s) for s in _sort_scenes(scene_models)]

    allowed_ext = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    image_paths: List[str] = []
    scene_image_modes_record: List[str] = []
    n_scenes = max(len(scenes_ordered), 1)

    for i, s in enumerate(scenes_ordered):
        key = f"scene_upload_{s.index}"
        files = form.getlist(key)
        val = files[0] if files else None
        is_upload = hasattr(val, "filename") and hasattr(val, "read")
        filename = getattr(val, "filename", None) if is_upload else None
        mode_key = f"scene_image_mode_{s.index}"
        mode_raw = form.get(mode_key)
        mode = mode_raw.strip().lower() if isinstance(mode_raw, str) else ""
        if mode not in {"upload", "generate", "placeholder"}:
            mode = "upload" if is_upload and bool(filename) else "placeholder"
        print(
            f"[manual-video] scene={s.index} mode={mode} "
            f"upload_detected={is_upload} filename={filename if filename else 'NONE'}"
        )
        base_path = images_dir / f"scene_{s.index}_manual"

        if mode == "generate":
            ai_scene_dir = images_dir / f"scene_{s.index}_manual_ai"
            generated = image_service.generate_images_for_keywords(
                topic=topic,
                per_scene_keywords=[s.keywords],
                output_dir=str(ai_scene_dir),
                visual_style=visual_style,
                aspect_ratio=aspect_ratio,
                scene_texts=[s.text],
            )
            if generated:
                dest = Path(generated[0]).resolve()
                print(f"[manual-video] scene={s.index} using image path: {dest} (source=generate)")
                image_paths.append(str(dest))
                scene_image_modes_record.append("generate")
                continue
            dest = Path(f"{base_path}_placeholder.png")
            image_service.write_placeholder_scene_image(
                topic=topic,
                keywords=s.keywords,
                scene_index=s.index,
                visual_style=visual_style,
                aspect_ratio=aspect_ratio,
                output_path=str(dest),
                scene_text=s.text,
            )
            print(f"[manual-video] scene={s.index} using image path: {dest.resolve()} (source=placeholder-from-generate-fallback)")
            image_paths.append(str(dest.resolve()))
            scene_image_modes_record.append("placeholder")
            continue

        if mode == "upload" and is_upload and filename:
            record_mode = "upload"
            suffix = Path(str(filename)).suffix.lower()
            if suffix not in allowed_ext:
                suffix = ".png"
            dest = Path(f"{base_path}_upload{suffix}")
            try:
                # val is duck-typed upload object from multipart parser.
                data = await val.read()
            except Exception as read_exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not read upload for scene {s.index}: {read_exc}",
                ) from read_exc
            if not data:
                dest = Path(f"{base_path}_placeholder.png")
                image_service.write_placeholder_scene_image(
                    topic=topic,
                    keywords=s.keywords,
                    scene_index=s.index,
                    visual_style=visual_style,
                    aspect_ratio=aspect_ratio,
                    output_path=str(dest),
                    scene_text=s.text,
                )
                print(
                    f"[manual-video] scene={s.index} upload payload empty; "
                    f"using image path: {dest.resolve()} (source=placeholder)"
                )
                record_mode = "placeholder"
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(data)
                # Verify file persisted and is not empty; otherwise fallback.
                if not dest.exists() or dest.stat().st_size <= 0:
                    fallback = Path(f"{base_path}_placeholder.png")
                    image_service.write_placeholder_scene_image(
                        topic=topic,
                        keywords=s.keywords,
                        scene_index=s.index,
                        visual_style=visual_style,
                        aspect_ratio=aspect_ratio,
                        output_path=str(fallback),
                        scene_text=s.text,
                    )
                    print(
                        f"[manual-video] scene={s.index} upload saved empty/missing; "
                        f"using image path: {fallback.resolve()} (source=placeholder-after-upload-check)"
                    )
                    dest = fallback
                    record_mode = "placeholder"
                else:
                    print(
                        f"[manual-video] scene={s.index} upload saved; "
                        f"using image path: {dest.resolve()} (source=upload)"
                    )
            # Ensure successful upload path is what enters renderer inputs.
            image_paths.append(str(dest.resolve()))
            scene_image_modes_record.append(record_mode)
            continue

        # upload mode with no new multipart file: reuse persisted path from scenes_json
        if mode == "upload" and not (is_upload and filename):
            safe_existing = _safe_resolved_file_under_dir(images_dir, s.image_path)
            if safe_existing:
                rp = str(safe_existing)
                print(f"[manual-video] scene={s.index} reusing image_path: {rp} (source=upload-reuse)")
                image_paths.append(rp)
                scene_image_modes_record.append("upload")
                continue

        # placeholder mode or upload mode without a usable file or path
        dest = Path(f"{base_path}_placeholder.png")
        image_service.write_placeholder_scene_image(
            topic=topic,
            keywords=s.keywords,
            scene_index=s.index,
            visual_style=visual_style,
            aspect_ratio=aspect_ratio,
            output_path=str(dest),
            scene_text=s.text,
        )
        print(f"[manual-video] scene={s.index} using image path: {dest.resolve()} (source=placeholder)")
        image_paths.append(str(dest.resolve()))
        scene_image_modes_record.append("placeholder")
        progress("images", 15 + (50 * (i + 1) / n_scenes))

    scenes_ordered = [
        orig.model_copy(update={"image_path": pth, "image_mode": m})
        for orig, pth, m in zip(scenes_ordered, image_paths, scene_image_modes_record)
    ]

    progress("narration", 72)
    if narration_source == "upload":
        audio_files = form.getlist("audio_upload")
        audio_val = audio_files[0] if audio_files else None
        is_audio_upload = hasattr(audio_val, "filename") and hasattr(audio_val, "read")
        audio_filename = getattr(audio_val, "filename", None) if is_audio_upload else None

        if is_audio_upload and audio_filename:
            allowed_audio_ext = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
            suffix = Path(str(audio_filename)).suffix.lower()
            if suffix not in allowed_audio_ext:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported audio extension '{suffix}'. Allowed: {sorted(allowed_audio_ext)}",
                )

            uploaded_audio_path = (audio_dir / f"uploaded_narration{suffix}").resolve()
            try:
                audio_bytes = await audio_val.read()
            except Exception as read_exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not read uploaded narration audio: {read_exc}",
                ) from read_exc

            uploaded_audio_path.parent.mkdir(parents=True, exist_ok=True)
            with open(uploaded_audio_path, "wb") as f:
                f.write(audio_bytes or b"")

            if not uploaded_audio_path.exists() or uploaded_audio_path.stat().st_size <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Uploaded narration audio is empty or could not be saved.",
                )

            print(f"[manual-video] uploaded narration saved: {uploaded_audio_path}")
            audio_path = str(uploaded_audio_path)
        else:
            path_raw = form.get("narration_audio_path")
            path_str = path_raw.strip() if isinstance(path_raw, str) else ""
            safe_narr = _safe_resolved_file_under_dir(audio_dir, path_str or None)
            if not safe_narr:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "When narration_source='upload', send audio_upload or a valid "
                        "narration_audio_path pointing to an existing file under your topic audio folder."
                    ),
                )
            audio_path = str(safe_narr)
            print(f"[manual-video] reusing narration from narration_audio_path: {audio_path}")
    else:
        audio_path = tts_service.text_to_speech(
            text=script_text,
            output_dir=str(audio_dir),
            filename="voiceover.mp3",
        )

    narr_resp_source: Optional[Literal["tts", "upload"]] = "tts"
    narr_resp_path: Optional[str] = None
    if narration_source == "upload":
        narr_resp_source = "upload"
        narr_resp_path = audio_path

    branding = _parse_branding_from_form(form)
    logo_up = form.get("branding_logo_upload")
    if logo_up is not None and hasattr(logo_up, "read"):
        saved_logo = await _save_branding_logo_upload(logo_up)
        if saved_logo:
            branding = _branding_render_kwargs(
                _parse_bool_form(form.get("branding_enabled")),
                str(saved_logo),
                _normalize_branding_position(form.get("branding_position")),
                _normalize_branding_size(form.get("branding_size")),
                _clamp_branding_opacity(form.get("branding_opacity")),
            )

    progress("rendering", 85)
    return _finalize_video_response(
        topic=topic,
        script_text=script_text,
        scenes_ordered=scenes_ordered,
        image_paths=image_paths,
        audio_path=audio_path,
        videos_dir=videos_dir,
        used_ai_flag=False,
        aspect_ratio=aspect_ratio,
        image_fit_mode=image_fit_mode,
        background_music=background_music,
        background_music_volume=background_music_volume,
        motion_effect=motion_effect,
        motion_intensity=motion_intensity,
        subtitle_style=subtitle_style,
        narration_source=narr_resp_source,
        narration_audio_path=narr_resp_path,
        **branding,
    )


@app.post("/manual-video", response_model=VideoResponse)
async def manual_video(request: Request):
    """
    Local manual flow: user script + optional image uploads per scene index.
    multipart/form-data fields:
      - topic (str)
      - script_text (str)
      - scenes_json (JSON array of Scene objects without image_url required)
      - narration_source (optional): tts | upload
      - narration_audio_path (optional str): when narration_source=upload and no audio_upload,
        reuse this file if it resolves under the topic audio directory
      - visual_style (optional)
      - duration_seconds (optional, ignored for render but kept for API parity)
      - style (optional, ignored)
    Optional file fields per scene: scene_upload_{scene.index}
    Per scene: scene_image_mode_{index} in {upload, generate, placeholder}.
    If mode is upload with no new scene_upload file, an existing image_path on that scene
    (under the topic images directory) is reused.
    """
    form = await request.form()
    return await _manual_video_from_form(form)


async def _save_branding_logo_upload(upload) -> Path | None:
    """Persist a multipart logo file under outputs/branding/current_logo.<ext>."""
    if upload is None or not hasattr(upload, "read"):
        return None
    filename = getattr(upload, "filename", None) or "logo.png"
    suffix = Path(str(filename)).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Logo must be .png, .jpg, .jpeg, or .webp",
        )
    try:
        raw = await upload.read()
    except Exception as read_exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read logo upload: {read_exc}",
        ) from read_exc
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Logo file is empty")
    dest = _branding_dir() / f"current_logo{suffix}"
    dest.write_bytes(raw)
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save logo")
    return dest.resolve()


@app.post("/branding/upload", response_model=BrandingUploadResponse)
async def branding_upload(logo: UploadFile = File(...)):
    """
    Upload a channel logo once; returns branding_logo_path for reuse across render modes.
    """
    saved = await _save_branding_logo_upload(logo)
    if not saved:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="logo file is required")
    return BrandingUploadResponse(
        branding_logo_path=str(saved),
        branding_logo_url=_path_to_media_url(saved),
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
                    'http://localhost:5173'
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


@app.post("/jobs/generate-video", response_model=RenderJobStartResponse)
def job_generate_video(req: VideoRequest):
    job_id = render_job_service.create_job("ai_generate")
    render_job_service.submit_job(job_id, lambda progress: _execute_generate_video(req, progress))
    return RenderJobStartResponse(job_id=job_id)


@app.post("/jobs/regenerate-video", response_model=RenderJobStartResponse)
def job_regenerate_video(req: ManualVideoRequest):
    job_id = render_job_service.create_job("regenerate")
    render_job_service.submit_job(
        job_id,
        lambda progress: _regenerate_from_manual_request(req, progress),
    )
    return RenderJobStartResponse(job_id=job_id)


@app.post("/jobs/manual-video", response_model=RenderJobStartResponse)
async def job_manual_video(request: Request):
    form = await request.form()
    snapshot = await _snapshot_multipart_form(form)
    job_id = render_job_service.create_job("manual_video")

    def _run(progress: ProgressFn) -> VideoResponse:
        return _run_async_in_thread(_manual_video_from_form(snapshot, progress))

    render_job_service.submit_job(job_id, _run)
    return RenderJobStartResponse(job_id=job_id)


@app.post("/jobs/render-subtitles-video", response_model=RenderJobStartResponse)
async def job_render_subtitles_video(request: Request):
    subtitle_style, subtitle_items, source_video, out_mp4, branding = await _prepare_subtitles_render(
        request,
    )
    job_id = render_job_service.create_job("render_subtitles")

    def _run(progress: ProgressFn) -> RenderSubtitlesVideoResponse:
        progress("preparing", 10)
        return _execute_render_subtitles(
            source_video=source_video,
            out_mp4=out_mp4,
            subtitle_items=subtitle_items,
            subtitle_style=subtitle_style,
            branding=branding,
            progress=progress,
        )

    render_job_service.submit_job(job_id, _run)
    return RenderJobStartResponse(job_id=job_id)


@app.get("/jobs/{job_id}", response_model=RenderJobStatus)
def get_render_job(job_id: str):
    rec = render_job_service.get_job(job_id)
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _job_record_to_status(rec)


@app.get("/jobs", response_model=RenderJobListResponse)
def list_render_jobs(limit: int = 20):
    jobs = [_job_record_to_status(rec) for rec in render_job_service.list_latest_jobs(limit=limit)]
    return RenderJobListResponse(jobs=jobs)


@app.get("/jobs/latest", response_model=RenderJobListResponse)
def list_render_jobs_latest(limit: int = 20):
    """Alias for listing recent jobs (recovery helper)."""
    jobs = [_job_record_to_status(rec) for rec in render_job_service.list_latest_jobs(limit=limit)]
    return RenderJobListResponse(jobs=jobs)