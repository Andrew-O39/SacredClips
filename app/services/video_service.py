import os
from pathlib import Path
from typing import List, Tuple

from moviepy import AudioFileClip, ColorClip, CompositeVideoClip, ImageClip, concatenate_videoclips

MIN_SCENE_CLIP = 0.25

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_MUSIC_DIR = _PROJECT_ROOT / "assets" / "music"

_MUSIC_FILENAMES = {
    "peaceful_piano": "peaceful_piano.mp3",
    "ambient_pad": "ambient_pad.mp3",
    "soft_strings": "soft_strings.mp3",
    "gentle_choir": "gentle_choir.mp3",
}

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


def _concatenate_audioclips_safe(clips: List):
    if not clips:
        raise ValueError("concatenate_audioclips_safe: empty clips")
    if len(clips) == 1:
        return clips[0]
    try:
        from moviepy import concatenate_audioclips

        return concatenate_audioclips(clips)
    except Exception:
        pass
    try:
        from moviepy.audio.AudioClip import concatenate_audioclips as cac

        return cac(clips)
    except Exception as exc:
        raise RuntimeError(f"concatenate_audioclips unavailable: {exc}") from exc


def _volume_scale_compat(clip, factor: float):
    try:
        return clip.with_volume_scaled(factor)
    except AttributeError:
        try:
            return clip.volumex(factor)
        except AttributeError:
            return clip


def _audio_fade_compat(clip, fade_in: float, fade_out: float):
    fi = max(0.0, float(fade_in))
    fo = max(0.0, float(fade_out))
    if fi <= 1e-6 and fo <= 1e-6:
        return clip
    try:
        out = clip
        if fi > 1e-6:
            out = out.audio_fadein(fi)
        if fo > 1e-6:
            out = out.audio_fadeout(fo)
        return out
    except AttributeError:
        return clip


def _resolve_music_path(background_music: str) -> str | None:
    if not background_music or background_music == "none":
        return None
    fn = _MUSIC_FILENAMES.get(background_music)
    if not fn:
        return None
    p = _MUSIC_DIR / fn
    if not p.is_file():
        print(f"[render_video] Background music file missing (skipping music): {p}")
        return None
    return str(p)


def _loop_music_to_duration(src: AudioFileClip, target_duration: float) -> AudioFileClip:
    md = float(src.duration or 0)
    td = float(target_duration)
    if md <= 0.01:
        return src
    if md >= td - 1e-6:
        return _subclip_compat(src, 0, td)

    pieces = []
    remain = td
    while remain > 1e-5:
        seg = min(md, remain)
        pieces.append(_subclip_compat(src, 0, seg))
        remain -= seg
    if len(pieces) == 1:
        return pieces[0]
    return _concatenate_audioclips_safe(pieces)


def _build_music_clip(music_path: str, target_duration: float, volume: float) -> AudioFileClip | None:
    try:
        base = AudioFileClip(music_path)
    except Exception as e:
        print(f"[render_video] Could not load background music '{music_path}': {e}")
        return None

    try:
        looped = _loop_music_to_duration(base, target_duration)
    except Exception as e:
        print(f"[render_video] Could not loop background music: {e}")
        try:
            base.close()
        except Exception:
            pass
        return None

    td = float(target_duration)
    fade_d = min(1.5, max(0.1, td / 8.0))
    faded = _audio_fade_compat(looped, fade_d, fade_d)
    scaled = _volume_scale_compat(faded, float(volume))

    try:
        dur_now = float(scaled.duration)
        if dur_now > td + 0.08:
            scaled = _subclip_compat(scaled, 0, td)
    except Exception:
        pass

    return scaled


def _compose_final_audio(
    narration_clip: AudioFileClip | None,
    video_duration: float,
    background_music: str,
    background_music_volume: float,
) -> tuple[AudioFileClip | None, bool]:
    """
    Returns (audio_clip_or_none, is_composite).
    is_composite=True means narration is embedded and should not be closed separately.
    """
    vd = max(0.01, float(video_duration))
    vol = float(background_music_volume)
    music_path = _resolve_music_path(background_music)

    music_clip: AudioFileClip | None = None
    if (
        music_path
        and background_music != "none"
        and vol > 1e-9
    ):
        music_clip = _build_music_clip(music_path, vd, vol)

    if narration_clip is not None and music_clip is not None:
        try:
            from moviepy import CompositeAudioClip as CompositeAudioClipType
        except ImportError:
            from moviepy.audio.AudioClip import CompositeAudioClip as CompositeAudioClipType  # type: ignore

        try:
            mixed = CompositeAudioClipType([narration_clip, music_clip]).with_duration(vd)
        except AttributeError:
            try:
                mixed = CompositeAudioClipType([narration_clip, music_clip]).set_duration(vd)
            except AttributeError:
                mixed = CompositeAudioClipType([narration_clip, music_clip])
        return mixed, True

    if narration_clip is not None:
        return narration_clip, False

    if music_clip is not None:
        return music_clip, False

    return None, False


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


def _attach_audio_and_write(
    video,
    clips: List,
    output_path: str,
    narration_clip: AudioFileClip | None,
    background_music: str,
    background_music_volume: float,
):
    vd = float(video.duration)
    final_audio, _ = _compose_final_audio(
        narration_clip,
        vd,
        background_music,
        background_music_volume,
    )

    if final_audio is not None:
        try:
            video = video.with_audio(final_audio)
        except AttributeError:
            video = video.set_audio(final_audio)

    video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")

    for c in clips:
        try:
            c.close()
        except Exception:
            pass
    try:
        video.close()
    except Exception:
        pass

    if final_audio is not None:
        try:
            final_audio.close()
        except Exception:
            pass


def render_video(
    image_paths: List[str],
    audio_path: str,
    scene_durations: List[float],
    output_dir: str,
    filename: str = "final_video.mp4",
    aspect_ratio: str = "16:9",
    image_fit_mode: str = "fit",
    background_music: str = "none",
    background_music_volume: float = 0.12,
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

        _attach_audio_and_write(
            video,
            clips,
            output_path,
            audio_clip,
            background_music,
            background_music_volume,
        )
        return output_path

    if audio_clip is not None:
        try:
            audio_clip.close()
        except Exception:
            pass
        audio_clip = None

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

    _attach_audio_and_write(
        video,
        clips,
        output_path,
        None,
        background_music,
        background_music_volume,
    )
    return output_path
