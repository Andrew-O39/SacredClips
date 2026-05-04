import os
from pathlib import Path
from typing import List

from moviepy import ImageClip, AudioFileClip, concatenate_videoclips

MIN_DURATION = 60.0  # seconds — only enforced when **no usable narration audio**
MAX_DURATION = 90.0  # seconds
MIN_SCENE_CLIP = 0.25  # shortest per-scene still


def _subclip_compat(clip, t0: float, t1: float):
    try:
        return clip.subclipped(t0, t1)  # MoviePy 2.x
    except AttributeError:
        return clip.subclip(t0, t1)     # MoviePy 1.x


def _normalize_durations(scene_durations: List[float]) -> List[float]:
    """Guarantee each duration is usable and sum is positive."""
    out = [max(MIN_SCENE_CLIP, float(d)) for d in scene_durations]
    return out


def _scale_scene_durations_to_target(scene_durations: List[float], target: float) -> List[float]:
    """
    Stretch or compress segment lengths so visual montage totals `target` seconds.
    """
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
    # Fix float drift on last clip
    drift = target - sum(scaled)
    if scaled:
        scaled[-1] = max(MIN_SCENE_CLIP, scaled[-1] + drift)
    return scaled


def _clips_from_images(image_paths: List[str], durations: List[float]) -> List[ImageClip]:
    clips: List[ImageClip] = []
    for img_path, duration in zip(image_paths, durations):
        safe_duration = max(float(duration), MIN_SCENE_CLIP)
        clip = ImageClip(img_path, duration=safe_duration)
        try:
            clip = clip.resized(height=1080)
        except AttributeError:
            clip = clip.resize(height=1080)
        clips.append(clip)
    return clips


def _scale_durations_when_no_audio(scene_durations: List[float]) -> List[float]:
    """Cap slideshow at MAX_DURATION; durations already reflect creative intent."""
    durations = _normalize_durations(scene_durations)
    total = sum(durations)
    cap = MAX_DURATION
    if total <= cap:
        return durations
    return _scale_scene_durations_to_target(durations, cap)


def render_video(
    image_paths: List[str],
    audio_path: str,
    scene_durations: List[float],
    output_dir: str,
    filename: str = "final_video.mp4",
) -> str:
    """
    Combine images + narration into a vertical MP4.

    When **usable** narration audio is present:
      - Stretch scene timing so the slideshow length matches narration (no silent trailing pad).
      - Final length follows audio length (still capped by MAX_DURATION for Shorts-ish limits).
      - Do **not** pad to MIN_DURATION with silent frames — short narration yields a shorter clip.

    When audio is missing or useless (silent placeholder): keep slideshow ≤ MAX_DURATION
    and optionally pad silent frames until MIN_DURATION (legacy offline demo behaviour).
    """
    os.makedirs(output_dir, exist_ok=True)
    output_path = str(Path(output_dir) / filename)

    if len(image_paths) != len(scene_durations):
        raise RuntimeError(
            f"render_video: mismatched lengths images={len(image_paths)} durations={len(scene_durations)}"
        )

    if not image_paths:
        raise RuntimeError("render_video: no image clips were created")

    use_audio_filesystem = (
        audio_path
        and os.path.exists(audio_path)
        and os.path.getsize(audio_path) > 0
    )

    audio_clip = None
    audio_duration: float | None = None
    narration_ok = False

    if use_audio_filesystem:
        try:
            audio_clip = AudioFileClip(audio_path)
            audio_duration = float(audio_clip.duration)
            narration_ok = audio_duration >= 0.5
            if narration_ok and audio_duration > MAX_DURATION:
                audio_clip = _subclip_compat(audio_clip, 0, MAX_DURATION)
                audio_duration = float(audio_clip.duration)
        except Exception as e:
            narration_ok = False
            print(f"[render_video] Could not inspect/load audio '{audio_path}': {e}")
            if audio_clip:
                audio_clip.close()
                audio_clip = None
            audio_duration = None

    if narration_ok and audio_duration is not None and audio_clip is not None:
        target_video = audio_duration
        scaled_durations = _scale_scene_durations_to_target(scene_durations, target_video)

        clips = _clips_from_images(image_paths, scaled_durations)

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

        final = video

        final.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")

        for c in clips:
            c.close()
        final.close()
        if audio_clip:
            audio_clip.close()
        return output_path

    # --- No narration: silent / placeholder slideshow (legacy behaviour with MIN pad)

    durations = _scale_durations_when_no_audio(scene_durations)
    clips = _clips_from_images(image_paths, durations)
    video = concatenate_videoclips(clips, method="compose")

    if video.duration > MAX_DURATION:
        video = _subclip_compat(video, 0, MAX_DURATION)

    final_slideshow = video

    if audio_clip:
        audio_clip.close()
        audio_clip = None

    if final_slideshow.duration < MIN_DURATION:
        pad = MIN_DURATION - final_slideshow.duration
        last_img_path = image_paths[-1]
        pad_clip = ImageClip(last_img_path, duration=pad)
        try:
            pad_clip = pad_clip.resized(height=1080)
        except AttributeError:
            pad_clip = pad_clip.resize(height=1080)
        final_slideshow = concatenate_videoclips([final_slideshow, pad_clip], method="compose")
        pad_clip.close()

    final_slideshow.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")

    for c in clips:
        c.close()
    final_slideshow.close()

    return output_path
