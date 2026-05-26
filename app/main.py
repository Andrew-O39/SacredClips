import json
from pathlib import Path
from typing import Any, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter, ValidationError

from . import config
from .schemas import (
    AspectRatio,
    BackgroundMusic,
    ImageFitMode,
    ManualVideoRequest,
    MotionEffect,
    MotionIntensity,
    PreviewSceneRequest,
    PreviewSceneResponse,
    Scene,
    SubtitleStyle,
    VideoRequest,
    VideoResponse,
    VisualStyle,
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
        p = Path(candidate).expanduser().resolve()
        parent = expected_parent.resolve()
        p.relative_to(parent)
        if p.is_file() and p.stat().st_size > 0:
            return p
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


def _regenerate_from_manual_request(req: ManualVideoRequest) -> VideoResponse:
    """
    Images + TTS + render from structured scenes & script_text (edited script / scenes).

    Reuses uploaded scene images and uploaded narration paths when the client resends them.
    """
    _, audio_dir, images_dir, videos_dir = _prepare_topic_dirs(req.topic)
    scenes_sorted = [_strip_scene_for_render(s) for s in _sort_scenes(req.scenes)]
    image_paths: List[str] = []
    scenes_for_finalize: List[Scene] = []

    for s in scenes_sorted:
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
    )


@app.post("/generate-video", response_model=VideoResponse)
def generate_video(req: VideoRequest):
    target_duration = _clamp_duration_by_aspect(req.duration_seconds, req.aspect_ratio)

    _, audio_dir, images_dir, videos_dir = _prepare_topic_dirs(req.topic)

    # 1) Script + scenes (AI or fallback)
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

    # 2) Generate images (one per scene)
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

    # 3) TTS audio from script_text
    audio_path = tts_service.text_to_speech(
        text=script_text,
        output_dir=str(audio_dir),
        filename="voiceover.mp3",
    )

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

    for s in scenes_ordered:
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

    scenes_ordered = [
        orig.model_copy(update={"image_path": pth, "image_mode": m})
        for orig, pth, m in zip(scenes_ordered, image_paths, scene_image_modes_record)
    ]

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