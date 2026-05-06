import os
from pathlib import Path
from typing import List, Tuple

from moviepy import AudioFileClip, ColorClip, CompositeVideoClip, ImageClip, concatenate_videoclips

MIN_SCENE_CLIP = 0.25

ASPECT_RESOLUTION: dict[str, Tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}

ASPECT_DURATION_BOUNDS: dict[str, Tuple[float, float]] = {
    "9:16": (60.0, 90.0),
    "16:9": (120.0, 600.0),
    "1:1": (60.0, 180.0),
}


def _subclip_compat(clip, t0: float, t1: float):
    try:
        return clip.subclipped(t0, t1)
    except AttributeError:
        return clip.subclip(t0, t1)


def _normalize_durations(scene_durations: List[float]) -> List[float]:
    return [max(MIN_SCENE_CLIP, float(d)) for d in scene_durations]


def _scale_scene_durations_to_target(scene_durations: List[float], target: float) -> List[float]:
    if target <= 0 or not scene_durations:
        return scene_durations
    durations = _normalize_durations(scene_durations)
    total = sum(durations)
    if total <= 1e-6:
        n = len(durations)
        return [target / max(n, 1)] * max(n, 1)
    scale = target / total
    scaled = [max(MIN_SCENE_CLIP, d * scale) for d in durations]
    s2 = sum(scaled)
    if s2 <= 1e-6:
        return scaled
    scaled = [d * target / s2 for d in scaled]
    drift = target - sum(scaled)
    if scaled:
        scaled[-1] = max(MIN_SCENE_CLIP, scaled[-1] + drift)
    return scaled


def _aspect_resolution(aspect_ratio: str) -> Tuple[int, int]:
    return ASPECT_RESOLUTION.get(aspect_ratio, ASPECT_RESOLUTION["16:9"])


def _duration_bounds(aspect_ratio: str) -> Tuple[float, float]:
    return ASPECT_DURATION_BOUNDS.get(aspect_ratio, ASPECT_DURATION_BOUNDS["16:9"])


def _frame_image_clip(img_path: str, duration: float, width: int, height: int, image_fit_mode: str):
    base = ImageClip(img_path, duration=duration)
    fit_mode = (image_fit_mode or "fit").strip().lower()

    if fit_mode == "fill":
        # Cover mode: preserve aspect ratio, then center-crop to frame.
        src_w = float(base.w)
        src_h = float(base.h)
        if src_w <= 0 or src_h <= 0:
            try:
                return base.resized(width=width, height=height)
            except AttributeError:
                return base.resize(width=width, height=height)

        scale = max(width / src_w, height / src_h)
        target_w = max(1, int(round(src_w * scale)))
        target_h = max(1, int(round(src_h * scale)))
        try:
            scaled = base.resized(width=target_w, height=target_h)
        except AttributeError:
            scaled = base.resize(width=target_w, height=target_h)

        x1 = max(0, int((target_w - width) / 2))
        y1 = max(0, int((target_h - height) / 2))
        x2 = x1 + width
        y2 = y1 + height
        try:
            return scaled.cropped(x1=x1, y1=y1, x2=x2, y2=y2)
        except AttributeError:
            return scaled.crop(x1=x1, y1=y1, x2=x2, y2=y2)

    # fit mode: keep full image and pad
    try:
        fg = base.resized(width=width)
    except AttributeError:
        fg = base.resize(width=width)

    if fg.h > height:
        try:
            fg = base.resized(height=height)
        except AttributeError:
            fg = base.resize(height=height)

    bg = ColorClip(size=(width, height), color=(18, 18, 24), duration=duration)
    x = (width - fg.w) / 2
    y = (height - fg.h) / 2

    try:
        fg = fg.with_position((x, y))
        comp = CompositeVideoClip([bg, fg], size=(width, height)).with_duration(duration)
    except AttributeError:
        fg = fg.set_position((x, y))
        comp = CompositeVideoClip([bg, fg], size=(width, height)).set_duration(duration)
    return comp


def _clips_from_images(
    image_paths: List[str],
    durations: List[float],
    aspect_ratio: str,
    image_fit_mode: str,
):
    clips = []
    width, height = _aspect_resolution(aspect_ratio)
    for img_path, duration in zip(image_paths, durations):
        safe_duration = max(float(duration), MIN_SCENE_CLIP)
        clips.append(_frame_image_clip(img_path, safe_duration, width, height, image_fit_mode))
    return clips


def _scale_durations_when_no_audio(scene_durations: List[float], aspect_ratio: str) -> List[float]:
    durations = _normalize_durations(scene_durations)
    total = sum(durations)
    _, max_d = _duration_bounds(aspect_ratio)
    if total <= max_d:
        return durations
    return _scale_scene_durations_to_target(durations, max_d)


def render_video(
    image_paths: List[str],
    audio_path: str,
    scene_durations: List[float],
    output_dir: str,
    filename: str = "final_video.mp4",
    aspect_ratio: str = "16:9",
    image_fit_mode: str = "fit",
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    output_path = str(Path(output_dir) / filename)

    if len(image_paths) != len(scene_durations):
        raise RuntimeError(
            f"render_video: mismatched lengths images={len(image_paths)} durations={len(scene_durations)}"
        )
    if not image_paths:
        raise RuntimeError("render_video: no image clips were created")

    min_d, max_d = _duration_bounds(aspect_ratio)

    use_audio = audio_path and os.path.exists(audio_path) and os.path.getsize(audio_path) > 0

    audio_clip = None
    audio_duration: float | None = None
    narration_ok = False

    if use_audio:
        try:
            audio_clip = AudioFileClip(audio_path)
            audio_duration = float(audio_clip.duration)
            narration_ok = audio_duration >= 0.5
            if narration_ok and audio_duration > max_d:
                audio_clip = _subclip_compat(audio_clip, 0, max_d)
                audio_duration = float(audio_clip.duration)
        except Exception as e:
            narration_ok = False
            print(f"[render_video] Could not inspect/load audio '{audio_path}': {e}")
            if audio_clip:
                audio_clip.close()
                audio_clip = None
            audio_duration = None

    if narration_ok and audio_duration is not None and audio_clip is not None:
        scaled_durations = _scale_scene_durations_to_target(scene_durations, audio_duration)
        clips = _clips_from_images(image_paths, scaled_durations, aspect_ratio, image_fit_mode)
        video = concatenate_videoclips(clips, method="compose")

        vd = float(video.duration)
        ad = float(audio_clip.duration)
        tolerance = 0.12
        try:
            if vd > ad + tolerance:
                video = _subclip_compat(video, 0, min(vd, ad))
            elif ad > vd + tolerance:
                audio_clip = _subclip_compat(audio_clip, 0, min(ad, vd))
        except Exception as e_sync:
            print(f"[render_video] sync trim fallback: {e_sync}")

        try:
            video = video.with_audio(audio_clip)
        except AttributeError:
            video = video.set_audio(audio_clip)

        video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")

        for c in clips:
            c.close()
        video.close()
        audio_clip.close()
        return output_path

    durations = _scale_durations_when_no_audio(scene_durations, aspect_ratio)
    clips = _clips_from_images(image_paths, durations, aspect_ratio, image_fit_mode)
    video = concatenate_videoclips(clips, method="compose")

    if video.duration > max_d:
        video = _subclip_compat(video, 0, max_d)

    if video.duration < min_d:
        pad = min_d - video.duration
        last_img_path = image_paths[-1]
        width, height = _aspect_resolution(aspect_ratio)
        pad_clip = _frame_image_clip(last_img_path, pad, width, height, image_fit_mode)
        video = concatenate_videoclips([video, pad_clip], method="compose")
        pad_clip.close()

    video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")

    for c in clips:
        c.close()
    video.close()

    return output_path
