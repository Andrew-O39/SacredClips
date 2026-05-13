import os
import re
import textwrap
import traceback
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from moviepy import AudioFileClip, ColorClip, CompositeVideoClip, ImageClip, concatenate_videoclips

MIN_SCENE_CLIP = 0.25

# Motion easing label for logs (smoothstep = x*x*(3-2*x)).
MOTION_EASING_NAME = "smoothstep"

# Zoom end scale (start is always 1.0) by motion_intensity — see _zoom_end_for_intensity.

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

SUBTITLE_MIN_CHUNK_SEC = 0.45
SUBTITLE_MAX_CHUNK_CHARS = 130

_SUBTITLE_STYLE_PARAMS: dict[str, dict[str, float | int]] = {
    "minimal": {
        "font_frac": 0.028,
        "margin_frac": 0.075,
        "max_width_frac": 0.88,
        "pad_x": 16,
        "pad_y": 10,
        "bg_alpha": 145,
        "stroke": 0,
        "bold": 0,
    },
    "cinematic": {
        "font_frac": 0.034,
        "margin_frac": 0.095,
        "max_width_frac": 0.82,
        "pad_x": 22,
        "pad_y": 12,
        "bg_alpha": 158,
        "stroke": 1,
        "bold": 0,
    },
    "shorts": {
        "font_frac": 0.042,
        "margin_frac": 0.115,
        "max_width_frac": 0.9,
        "pad_x": 18,
        "pad_y": 12,
        "bg_alpha": 178,
        "stroke": 2,
        "bold": 1,
    },
}

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)


def _normalize_subtitle_style(raw: object) -> str:
    s = (raw if isinstance(raw, str) else str(raw or "")).strip().lower()
    if s in ("off", "minimal", "cinematic", "shorts"):
        return s
    return "off"


def _load_subtitle_font(size: int, bold: bool) -> ImageFont.ImageFont:
    candidates: List[str] = []
    if bold:
        candidates.extend(
            [
                p
                for p in _FONT_CANDIDATES
                if "Bold" in p or "bd.ttf" in p.lower() or "Sans-Bold" in p
            ]
        )
    candidates.extend([p for p in _FONT_CANDIDATES if p not in candidates])
    for path in candidates:
        try:
            if os.path.isfile(path):
                return ImageFont.truetype(path, size=max(12, int(size)))
        except OSError:
            continue
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=max(12, int(size)))
    except OSError:
        return ImageFont.load_default()


def _split_sentence_chunks(text: str) -> List[str]:
    t = (text or "").strip()
    if not t:
        return []
    parts = re.split(r"(?<=[.!?])\s+", t)
    out = [p.strip() for p in parts if p.strip()]
    return out if out else [t]


def _merge_short_fragments(parts: List[str], min_len: int = 14) -> List[str]:
    if not parts:
        return []
    merged: List[str] = []
    buf = parts[0]
    for p in parts[1:]:
        if len(buf) < min_len or len(p) < min_len:
            buf = f"{buf.rstrip()} {p.lstrip()}"
        else:
            merged.append(buf)
            buf = p
    merged.append(buf)
    return merged


def _merge_until_chunk_budget(parts: List[str], max_chunks: int) -> List[str]:
    cur = list(parts)
    max_chunks = max(1, max_chunks)
    while len(cur) > max_chunks:
        best_i = 0
        best = len(cur[0]) + len(cur[1])
        for i in range(len(cur) - 1):
            s = len(cur[i]) + len(cur[i + 1])
            if s < best:
                best = s
                best_i = i
        cur = cur[:best_i] + [f"{cur[best_i].rstrip()} {cur[best_i + 1].lstrip()}"] + cur[best_i + 2 :]
    return cur


def _chunk_subtitle_text_for_scene(text: str, scene_duration: float) -> List[str]:
    d = max(float(scene_duration), MIN_SCENE_CLIP)
    max_chunks = max(1, min(36, int(d / SUBTITLE_MIN_CHUNK_SEC)))
    raw = _split_sentence_chunks(text)
    parts = _merge_short_fragments(raw)
    if not parts:
        return [""]
    parts = _merge_until_chunk_budget(parts, max_chunks)
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if len(p) > SUBTITLE_MAX_CHUNK_CHARS:
            p = p[: SUBTITLE_MAX_CHUNK_CHARS - 3].rstrip() + "..."
        if p:
            out.append(p)
    return out if out else [""]


def _wrap_two_lines(text: str, draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    """At most two lines; trim with ... to fit max_width."""
    t = text.replace("\n", " ").strip()
    if not t:
        return [""]
    bbox = draw.textbbox((0, 0), "M", font=font)
    cw = max(1.0, float(bbox[2] - bbox[0]))
    cols = max(18, int(max_width / cw))
    parts = textwrap.wrap(t, width=cols, break_long_words=True, break_on_hyphens=False)
    if not parts:
        return [t[:cols] + "..."]
    if len(parts) <= 2:
        lines = parts[:2]
    else:
        mid = max(1, len(parts) // 2)
        lines = [" ".join(parts[:mid]).strip(), " ".join(parts[mid:]).strip()]

    def _trim(s: str) -> str:
        s = s.strip()
        if not s:
            return ""
        while len(s) > 4:
            bb = draw.textbbox((0, 0), s, font=font)
            if bb[2] - bb[0] <= max_width:
                return s
            s = s[:-4].rstrip() + "..."
        return s[:3] + "..."

    out = [_trim(lines[0])]
    if len(lines) > 1 and lines[1]:
        out.append(_trim(lines[1]))
    return out if out[0] else [""]


def _render_subtitle_rgba_frame(
    width: int,
    height: int,
    text: str,
    style: str,
) -> np.ndarray:
    cfg = _SUBTITLE_STYLE_PARAMS.get(style, _SUBTITLE_STYLE_PARAMS["minimal"])
    font_frac = float(cfg["font_frac"])
    margin_frac = float(cfg["margin_frac"])
    max_width_frac = float(cfg["max_width_frac"])
    pad_x = int(cfg["pad_x"])
    pad_y = int(cfg["pad_y"])
    bg_alpha = int(cfg["bg_alpha"])
    stroke_w = int(cfg["stroke"])
    bold = bool(int(cfg["bold"]))

    img = Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_size = max(14, int(height * font_frac))
    font = _load_subtitle_font(font_size, bold=bold)
    max_text_w = int(width * max_width_frac)

    lines = _wrap_two_lines(text.strip(), draw, font, max_text_w)
    joined = "\n".join(lines)
    bbox = draw.multiline_textbbox((0, 0), joined, font=font, spacing=4, stroke_width=stroke_w if stroke_w else 0)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    box_w = min(int(width * 0.94), tw + 2 * pad_x)
    box_h = th + 2 * pad_y
    margin_bottom = int(height * margin_frac)
    x0 = (width - box_w) // 2
    y0 = height - margin_bottom - box_h
    y0 = min(y0, height - box_h - int(height * 0.02))
    y0 = max(0, y0)

    overlay = Image.new("RGBA", (box_w, box_h), (12, 12, 18, bg_alpha))
    img.paste(overlay, (x0, y0), overlay)

    tx = x0 + pad_x - bbox[0]
    ty = y0 + pad_y - bbox[1]
    text_kw: dict = {
        "font": font,
        "fill": (248, 248, 252, 255),
        "spacing": 4,
    }
    if stroke_w > 0:
        text_kw["stroke_width"] = stroke_w
        text_kw["stroke_fill"] = (10, 10, 14, 255)
    draw.multiline_text((tx, ty), joined, **text_kw)
    return np.asarray(img, dtype=np.uint8)


def _imageclip_from_rgba(rgba: np.ndarray, duration: float):
    """MoviePy composites alpha correctly when provided as a mask clip."""
    rgb = np.ascontiguousarray(rgba[:, :, :3], dtype=np.uint8)
    alpha = rgba[:, :, 3].astype(np.float32) / 255.0
    try:
        mask = ImageClip(alpha, is_mask=True, duration=duration)
        clip = ImageClip(rgb, duration=duration).with_mask(mask)
        return clip
    except Exception:
        try:
            return ImageClip(rgba, duration=duration, transparent=True)
        except TypeError:
            return ImageClip(rgb, duration=duration)


def _build_subtitle_strip_clip(
    text: str,
    scene_duration: float,
    width: int,
    height: int,
    style: str,
):
    chunks = _chunk_subtitle_text_for_scene(text, scene_duration)
    n = len(chunks)
    d = max(float(scene_duration), MIN_SCENE_CLIP)
    each = d / n
    sub_clips = []
    for ch in chunks:
        rgba = _render_subtitle_rgba_frame(width, height, ch, style)
        sub_clips.append(_imageclip_from_rgba(rgba, each))
    if len(sub_clips) == 1:
        strip = sub_clips[0]
    else:
        strip = concatenate_videoclips(sub_clips, method="compose")
    try:
        strip = strip.with_duration(d)
    except AttributeError:
        strip = strip.set_duration(d)
    return strip


def _maybe_composite_subtitles(
    scene_clip,
    scene_text: str,
    scene_duration: float,
    width: int,
    height: int,
    subtitle_style: str,
):
    ss = _normalize_subtitle_style(subtitle_style)
    if ss == "off":
        return scene_clip
    if not (scene_text or "").strip():
        return scene_clip
    d = max(float(scene_duration), MIN_SCENE_CLIP)
    try:
        strip = _build_subtitle_strip_clip(scene_text, d, width, height, ss)
        try:
            out = CompositeVideoClip([scene_clip, strip], size=(int(width), int(height))).with_duration(d)
        except AttributeError:
            out = CompositeVideoClip([scene_clip, strip], size=(int(width), int(height))).set_duration(d)
        return out
    except Exception as exc:
        print(f"[render_video] subtitles skipped for a scene: {exc!r}")
        traceback.print_exc()
        return scene_clip


def _scene_log_tag(scene_index: Optional[int]) -> str:
    if scene_index is None:
        return ""
    if scene_index < 0:
        return "scene=pad "
    return f"scene={scene_index} "


def _normalize_motion_intensity(raw: object) -> str:
    s = (raw if isinstance(raw, str) else str(raw or "")).strip().lower()
    if s in ("subtle", "medium", "strong"):
        return s
    return "subtle"


def _zoom_end_for_intensity(motion_intensity: str) -> float:
    """Max uniform scale over the scene (1.0 -> end)."""
    mi = _normalize_motion_intensity(motion_intensity)
    return {"subtle": 1.14, "medium": 1.18, "strong": 1.25}.get(mi, 1.14)


def _slow_pan_geometry(
    width: int,
    height: int,
    motion_intensity: str,
    *,
    strength_scale: float = 1.0,
) -> tuple[int, int, int]:
    """
    Pan distance (pixels) and widened frame size for horizontal pan.
    strength_scale < 1 reduces pan (e.g. Ken Burns vs full slow_pan).
    """
    mi = _normalize_motion_intensity(motion_intensity)
    if mi == "strong":
        frac, widen = 0.036, 1.078
    elif mi == "medium":
        frac, widen = 0.028, 1.056
    else:
        frac, widen = 0.017, 1.034
    pan_px = max(1, int(frac * int(width) * float(strength_scale)))
    nw = max(width + 1, int(round(width * widen)))
    nh = int(height)
    return pan_px, nw, nh


def _ken_burns_pan_strength_scale(motion_intensity: str) -> float:
    mi = _normalize_motion_intensity(motion_intensity)
    return {"subtle": 0.50, "medium": 0.68, "strong": 0.88}.get(mi, 0.50)


def _subclip_compat(clip, t0: float, t1: float):
    try:
        return clip.subclipped(t0, t1)
    except AttributeError:
        return clip.subclip(t0, t1)


def _smoothstep(x: float) -> float:
    x = min(max(float(x), 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def _duration_bucket_label(duration: float) -> str:
    """Scene length class for adaptive motion (used in logs + progression)."""
    d = max(float(duration), MIN_SCENE_CLIP)
    if d < 4.0:
        return "short"
    if d <= 8.0:
        return "medium"
    return "long"


def _motion_u_adaptive(t: float, duration: float) -> float:
    """
    Map wall-clock t/d to a shaped 0..1 value before easing.
    Short scenes: gamma < 1 so motion advances earlier (more visible in a few seconds).
    Long scenes: gamma > 1 for a calmer, documentary-style build.
    """
    d = max(float(duration), MIN_SCENE_CLIP)
    u = min(max(t / d, 0.0), 1.0)
    if d < 4.0:
        gamma = 0.58
    elif d > 8.0:
        gamma = 1.22
    else:
        gamma = 1.0
    return min(max(u**gamma, 0.0), 1.0)


def _motion_progress_eased(t: float, duration: float) -> float:
    """Adaptive linear clock -> smoothstep for organic in/out feel."""
    return _smoothstep(_motion_u_adaptive(t, duration))


def _gentle_zoom_scale(t: float, duration: float, zoom_end: float) -> float:
    p = _motion_progress_eased(t, duration)
    return 1.0 + (float(zoom_end) - 1.0) * p


def _frame_rgb_uint8(frame: np.ndarray) -> np.ndarray:
    """Normalize MoviePy frame to HxWx3 uint8 RGB."""
    if frame is None or frame.size == 0:
        raise ValueError("empty frame")
    if frame.ndim == 2:
        arr = np.stack([frame, frame, frame], axis=-1)
    else:
        arr = frame[:, :, :3] if frame.shape[2] >= 3 else np.repeat(frame[:, :, :1], 3, axis=2)
    if arr.dtype == np.uint8:
        return np.ascontiguousarray(arr)
    a = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
    mx = float(np.max(a)) if a.size else 0.0
    if mx <= 1.0 + 1e-5:
        out = (np.clip(a, 0.0, 1.0) * 255.0).astype(np.uint8)
    else:
        out = np.clip(a, 0.0, 255.0).astype(np.uint8)
    return np.ascontiguousarray(out)


def _center_crop_u8(arr: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Crop arr (HxWxC) to target_h x target_w from center; pad with zeros if too small."""
    h, w = int(arr.shape[0]), int(arr.shape[1])
    c = int(arr.shape[2]) if arr.ndim >= 3 else 1
    if h >= target_h and w >= target_w:
        y0 = max(0, (h - target_h) // 2)
        x0 = max(0, (w - target_w) // 2)
        return np.ascontiguousarray(arr[y0 : y0 + target_h, x0 : x0 + target_w])
    out = np.zeros((target_h, target_w, c), dtype=np.uint8)
    copy_h = min(h, target_h)
    copy_w = min(w, target_w)
    y0o = (target_h - copy_h) // 2
    x0o = (target_w - copy_w) // 2
    out[y0o : y0o + copy_h, x0o : x0o + copy_w] = arr[:copy_h, :copy_w]
    return out


def _gentle_zoom_frame_filter(duration: float, target_h: int, target_w: int, zoom_end: float):
    """
    MoviePy 2 transform: func(get_frame, t) -> frame array (H,W,C) at constant size.
    Zoom by scaling the frame up then center-cropping back to target size.
    """

    def filt(get_frame, t: float) -> np.ndarray:
        frame = get_frame(t)
        rgb = _frame_rgb_uint8(frame)
        h, w = rgb.shape[0], rgb.shape[1]
        s = _gentle_zoom_scale(t, duration, zoom_end)
        nh = max(2, int(round(h * s)))
        nw = max(2, int(round(w * s)))
        img = Image.fromarray(rgb)
        scaled = np.asarray(img.resize((nw, nh), Image.Resampling.LANCZOS), dtype=np.uint8)
        return _center_crop_u8(scaled, target_h, target_w)

    return filt


def _motion_gentle_zoom(clip, duration: float, width: int, height: int, zoom_end: float):
    """
    Per-frame zoom (reliable in MoviePy 2.x). Output stays exactly width x height.
    """
    d = max(float(duration), MIN_SCENE_CLIP)
    th, tw = int(height), int(width)
    filt = _gentle_zoom_frame_filter(d, th, tw, float(zoom_end))
    return clip.transform(filt, apply_to=[], keep_duration=True)


def _motion_slow_pan(
    clip,
    duration: float,
    width: int,
    height: int,
    motion_intensity: str,
    *,
    strength_scale: float = 1.0,
):
    d = max(float(duration), MIN_SCENE_CLIP)
    pan_px, nw, nh = _slow_pan_geometry(width, height, motion_intensity, strength_scale=strength_scale)
    z = None
    try:
        z = clip.resized(new_size=(nw, nh))
    except Exception:
        try:
            z = clip.resized(width=nw, height=nh)
        except Exception:
            try:
                z = clip.resize(width=nw, height=nh)
            except Exception:
                raise RuntimeError("slow_pan: resize unsupported") from None

    def pos_fn(t: float):
        p = _motion_progress_eased(t, d)
        x = -pan_px * p
        y = (height - nh) / 2
        return (x, y)

    bg = ColorClip(size=(width, height), color=(18, 18, 24), duration=d)
    try:
        fg = z.with_position(pos_fn)
        comp = CompositeVideoClip([bg, fg], size=(width, height)).with_duration(d)
    except AttributeError:
        fg = z.set_position(pos_fn)
        comp = CompositeVideoClip([bg, fg], size=(width, height)).set_duration(d)
    return comp


def _motion_ken_burns(clip, duration: float, width: int, height: int, motion_intensity: str):
    """Combined zoom + pan; pan strength follows intensity."""
    d = max(float(duration), MIN_SCENE_CLIP)
    zoom_end = _zoom_end_for_intensity(motion_intensity)
    z = _motion_gentle_zoom(clip, d, width, height, zoom_end)
    try:
        pan_scale = _ken_burns_pan_strength_scale(motion_intensity)
        return _motion_slow_pan(z, d, width, height, motion_intensity, strength_scale=pan_scale)
    except Exception as exc:
        print(f"[motion] ken_burns: slow_pan failed, using zoom-only: {exc!r}")
        traceback.print_exc()
        return z


def _apply_motion_to_clip(
    clip,
    motion_effect: str,
    width: int,
    height: int,
    duration: float,
    scene_index: Optional[int] = None,
    motion_intensity: str = "subtle",
):
    me = (motion_effect or "none").strip().lower()
    mi = _normalize_motion_intensity(motion_intensity)
    zoom_end = _zoom_end_for_intensity(mi)
    if me in ("", "none"):
        d = max(float(duration), MIN_SCENE_CLIP)
        W, H = int(width), int(height)
        tag = _scene_log_tag(scene_index)
        print(
            f"[motion] {tag}effect={me!r} intensity={mi!r} (ignored) duration={d:.3f}s "
            f"duration_bucket={_duration_bucket_label(d)!r} target={W}x{H} "
            f"applied=NO (static by choice)"
        )
        return clip
    d = max(float(duration), MIN_SCENE_CLIP)
    W, H = int(width), int(height)
    tag = _scene_log_tag(scene_index)
    bucket = _duration_bucket_label(d)
    easing = MOTION_EASING_NAME
    try:
        if me == "gentle_zoom":
            out = _motion_gentle_zoom(clip, d, W, H, zoom_end)
            print(
                f"[motion] {tag}effect={me!r} intensity={mi!r} duration={d:.3f}s "
                f"duration_bucket={bucket!r} easing={easing!r} target={W}x{H} "
                f"applied=YES method=frame_transform zoom=1.00->{zoom_end:.2f}"
            )
            return out
        if me == "slow_pan":
            out = _motion_slow_pan(clip, d, W, H, mi, strength_scale=1.0)
            pan_px, nw, _ = _slow_pan_geometry(W, H, mi, strength_scale=1.0)
            print(
                f"[motion] {tag}effect={me!r} intensity={mi!r} duration={d:.3f}s "
                f"duration_bucket={bucket!r} easing={easing!r} target={W}x{H} "
                f"applied=YES method=resize_position pan_px={pan_px} canvas_w={nw}"
            )
            return out
        if me == "ken_burns":
            out = _motion_ken_burns(clip, d, W, H, mi)
            pan_px, nw, _ = _slow_pan_geometry(
                W, H, mi, strength_scale=_ken_burns_pan_strength_scale(mi)
            )
            print(
                f"[motion] {tag}effect={me!r} intensity={mi!r} duration={d:.3f}s "
                f"duration_bucket={bucket!r} easing={easing!r} target={W}x{H} "
                f"applied=YES method=ken_burns zoom=1.00->{zoom_end:.2f} pan_px≈{pan_px} canvas_w≈{nw}"
            )
            return out
        print(
            f"[motion] {tag}effect={me!r} intensity={mi!r} duration={d:.3f}s "
            f"duration_bucket={bucket!r} easing={easing!r} target={W}x{H} "
            f"applied=NO (unknown effect, static)"
        )
        return clip
    except Exception as exc:
        print(
            f"[motion] {tag}effect={me!r} intensity={mi!r} duration={d:.3f}s "
            f"duration_bucket={bucket!r} easing={easing!r} target={W}x{H} "
            f"applied=FALLBACK_STATIC reason={exc!r}"
        )
        traceback.print_exc()
    return clip


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


def _frame_image_clip(
    img_path: str,
    duration: float,
    width: int,
    height: int,
    image_fit_mode: str,
    motion_effect: str = "none",
    scene_index: Optional[int] = None,
    motion_intensity: str = "subtle",
):
    base = ImageClip(img_path, duration=duration)
    fit_mode = (image_fit_mode or "fit").strip().lower()
    static_clip = None

    if fit_mode == "fill":
        # Cover mode: preserve aspect ratio, then center-crop to frame.
        src_w = float(base.w)
        src_h = float(base.h)
        if src_w <= 0 or src_h <= 0:
            try:
                static_clip = base.resized(width=width, height=height)
            except AttributeError:
                static_clip = base.resize(width=width, height=height)
        else:
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
                static_clip = scaled.cropped(x1=x1, y1=y1, x2=x2, y2=y2)
            except AttributeError:
                static_clip = scaled.crop(x1=x1, y1=y1, x2=x2, y2=y2)

    if static_clip is None:
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
            static_clip = CompositeVideoClip([bg, fg], size=(width, height)).with_duration(duration)
        except AttributeError:
            fg = fg.set_position((x, y))
            static_clip = CompositeVideoClip([bg, fg], size=(width, height)).set_duration(duration)

    return _apply_motion_to_clip(
        static_clip,
        motion_effect,
        width,
        height,
        duration,
        scene_index=scene_index,
        motion_intensity=motion_intensity,
    )


def _clips_from_images(
    image_paths: List[str],
    durations: List[float],
    aspect_ratio: str,
    image_fit_mode: str,
    motion_effect: str = "gentle_zoom",
    motion_intensity: str = "subtle",
    subtitle_style: str = "off",
    subtitle_texts: Optional[List[str]] = None,
):
    clips = []
    width, height = _aspect_resolution(aspect_ratio)
    ss = _normalize_subtitle_style(subtitle_style)
    texts = subtitle_texts or []
    for idx, (img_path, duration) in enumerate(zip(image_paths, durations), start=1):
        safe_duration = max(float(duration), MIN_SCENE_CLIP)
        clip = _frame_image_clip(
            img_path,
            safe_duration,
            width,
            height,
            image_fit_mode,
            motion_effect=motion_effect,
            scene_index=idx,
            motion_intensity=motion_intensity,
        )
        if ss != "off" and idx - 1 < len(texts):
            clip = _maybe_composite_subtitles(
                clip, texts[idx - 1], safe_duration, width, height, ss
            )
        clips.append(clip)
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
    motion_effect: str = "gentle_zoom",
    motion_intensity: str = "subtle",
    subtitle_style: str = "off",
    subtitle_texts: Optional[List[str]] = None,
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
    mi = _normalize_motion_intensity(motion_intensity)
    ss = _normalize_subtitle_style(subtitle_style)
    st_list = list(subtitle_texts) if subtitle_texts else []
    while len(st_list) < len(image_paths):
        st_list.append("")
    st_list = st_list[: len(image_paths)]
    print(
        f"[render_video] motion_effect={motion_effect!r} motion_intensity={mi!r} "
        f"subtitle_style={ss!r} n_scenes={len(image_paths)} "
        f"aspect_ratio={aspect_ratio!r} image_fit_mode={image_fit_mode!r}"
    )

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
        print(
            f"[render_video] scene_durations_s count={len(scaled_durations)} "
            f"min={min(scaled_durations):.2f} max={max(scaled_durations):.2f} "
            f"sum={sum(scaled_durations):.2f} (per-scene motion logs follow)"
        )
        clips = _clips_from_images(
            image_paths,
            scaled_durations,
            aspect_ratio,
            image_fit_mode,
            motion_effect,
            motion_intensity=mi,
            subtitle_style=ss,
            subtitle_texts=st_list,
        )
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
    print(
        f"[render_video] scene_durations_s count={len(durations)} "
        f"min={min(durations):.2f} max={max(durations):.2f} sum={sum(durations):.2f} "
        f"(per-scene motion logs follow)"
    )
    clips = _clips_from_images(
        image_paths,
        durations,
        aspect_ratio,
        image_fit_mode,
        motion_effect,
        motion_intensity=mi,
        subtitle_style=ss,
        subtitle_texts=st_list,
    )
    video = concatenate_videoclips(clips, method="compose")

    if video.duration > max_d:
        video = _subclip_compat(video, 0, max_d)

    if video.duration < min_d:
        pad = min_d - video.duration
        last_img_path = image_paths[-1]
        width, height = _aspect_resolution(aspect_ratio)
        pad_clip = _frame_image_clip(
            last_img_path,
            pad,
            width,
            height,
            image_fit_mode,
            motion_effect=motion_effect,
            scene_index=-1,
            motion_intensity=mi,
        )
        if ss != "off" and st_list:
            pad_clip = _maybe_composite_subtitles(
                pad_clip, st_list[-1], pad, width, height, ss
            )
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
