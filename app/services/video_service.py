import os
import re
import traceback
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from moviepy import AudioFileClip, ColorClip, CompositeVideoClip, ImageClip, VideoFileClip, concatenate_videoclips

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

SUBTITLE_MIN_CHUNK_SEC = 0.40
# Long landscape chunks; shorts / 9:16 use tighter caps so lines fit without truncation.
SUBTITLE_MAX_CHUNK_CHARS_DEFAULT = 130
SUBTITLE_MAX_CHUNK_CHARS_SHORTS = 68
# When allowing more subtitle cards per scene (shorts / vertical), use a slightly shorter floor.
SUBTITLE_CHUNK_FLOOR_SEC_SHORTS = 0.36

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
        "max_lines": 2,
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
        "max_lines": 2,
    },
    "shorts": {
        "font_frac": 0.042,
        "margin_frac": 0.115,
        "max_width_frac": 0.9,
        "pad_x": 16,
        "pad_y": 11,
        "bg_alpha": 178,
        "stroke": 2,
        "bold": 1,
        "max_lines": 3,
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


def _normalize_branding_position(raw: object) -> str:
    s = (raw if isinstance(raw, str) else str(raw or "")).strip().lower()
    if s in ("top_left", "top_right", "bottom_left", "bottom_right"):
        return s
    return "bottom_right"


def _normalize_branding_size(raw: object) -> str:
    s = (raw if isinstance(raw, str) else str(raw or "")).strip().lower()
    if s in ("small", "medium", "large"):
        return s
    return "medium"


def _clamp_branding_opacity(raw: object) -> float:
    if raw is None or raw == "":
        return 0.8
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.8
    return max(0.0, min(1.0, v))


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


def _split_clauses_fine(text: str) -> List[str]:
    """Split on commas / semicolons / colons for shorter subtitle units (Shorts / vertical)."""
    t = (text or "").strip()
    if not t:
        return []
    parts = re.split(r"(?<=[,;:])\s+", t)
    out = [p.strip() for p in parts if p.strip()]
    return out if out else [t]


def _split_long_piece_by_words(piece: str, max_chars: int) -> List[str]:
    """Word-wrap a long clause into multiple chunks without mid-word truncation when possible."""
    piece = piece.strip()
    if not piece:
        return []
    if len(piece) <= max_chars:
        return [piece]
    words = piece.split()
    chunks: List[str] = []
    buf: List[str] = []
    cur = 0
    for w in words:
        add = len(w) + (1 if buf else 0)
        if cur + add <= max_chars:
            buf.append(w)
            cur += add
        else:
            if buf:
                chunks.append(" ".join(buf))
            if len(w) > max_chars:
                for i in range(0, len(w), max(1, max_chars - 8)):
                    chunks.append(w[i : i + max(1, max_chars - 8)])
                buf = []
                cur = 0
            else:
                buf = [w]
                cur = len(w)
    if buf:
        chunks.append(" ".join(buf))
    return chunks if chunks else [piece[:max_chars]]


def _split_subtitle_fragments(text: str, fine_split: bool) -> List[str]:
    """Sentence-based split; optional secondary split for Shorts / 9:16."""
    t = (text or "").strip()
    if not t:
        return []
    sentences = _split_sentence_chunks(t)
    if not fine_split:
        return sentences
    fine: List[str] = []
    for sent in sentences:
        for clause in _split_clauses_fine(sent):
            fine.extend(_split_long_piece_by_words(clause, SUBTITLE_MAX_CHUNK_CHARS_SHORTS))
    return fine if fine else sentences


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


def _chunk_subtitle_text_for_scene(
    text: str,
    scene_duration: float,
    aspect_ratio: str,
    subtitle_style: str,
) -> List[str]:
    d = max(float(scene_duration), MIN_SCENE_CLIP)
    ss = _normalize_subtitle_style(subtitle_style)
    fine = aspect_ratio == "9:16" or ss == "shorts"
    floor_sec = SUBTITLE_CHUNK_FLOOR_SEC_SHORTS if fine else SUBTITLE_MIN_CHUNK_SEC
    max_chunks = max(1, min(52 if fine else 36, int(d / floor_sec)))
    max_chars = SUBTITLE_MAX_CHUNK_CHARS_SHORTS if fine else SUBTITLE_MAX_CHUNK_CHARS_DEFAULT

    raw = _split_subtitle_fragments(text, fine_split=fine)
    min_frag = 8 if fine else 14
    parts = _merge_short_fragments(raw, min_len=min_frag)
    if not parts:
        return [""]
    parts = _merge_until_chunk_budget(parts, max_chunks)

    out: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_chars:
            out.append(p)
        else:
            out.extend(_split_long_piece_by_words(p, max_chars))
    return out if out else [""]


def _line_width(draw: ImageDraw.ImageDraw, s: str, font: ImageFont.ImageFont, stroke_w: int) -> float:
    bb = draw.textbbox((0, 0), s, font=font, stroke_width=stroke_w or 0)
    return float(bb[2] - bb[0])


def _truncate_with_ellipsis(
    draw: ImageDraw.ImageDraw,
    s: str,
    font: ImageFont.ImageFont,
    max_width: float,
    stroke_w: int,
) -> str:
    s = s.strip()
    if not s:
        return ""
    if _line_width(draw, s, font, stroke_w) <= max_width:
        return s
    ell = "…"
    ew = _line_width(draw, ell, font, stroke_w)
    if ew > max_width:
        return ""
    lo, hi = 0, len(s)
    best = ell
    while lo <= hi:
        mid = (lo + hi) // 2
        trial = (s[:mid].rstrip() + ell).strip()
        if _line_width(draw, trial, font, stroke_w) <= max_width:
            best = trial
            lo = mid + 1
        else:
            hi = mid - 1
    return best if best.strip() else ell


def _wrap_subtitle_lines(
    text: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    max_width: float,
    max_lines: int,
    stroke_w: int,
) -> List[str]:
    """Greedy word wrap to at most max_lines; ellipsis only when a token cannot fit."""
    t = text.replace("\n", " ").strip()
    if not t:
        return [""]
    words = t.split()
    lines: List[str] = []
    remaining = list(words)
    sw = stroke_w or 0

    def join_ws(ws: List[str]) -> str:
        return " ".join(ws).strip()

    while remaining and len(lines) < max_lines:
        line_words: List[str] = []
        while remaining:
            w0 = remaining[0]
            trial = join_ws(line_words + [w0]) if line_words else w0
            if _line_width(draw, trial, font, sw) <= max_width:
                line_words.append(remaining.pop(0))
            else:
                break
        if line_words:
            lines.append(join_ws(line_words))
        elif remaining:
            w0 = remaining.pop(0)
            lines.append(_truncate_with_ellipsis(draw, w0, font, max_width, sw))
        else:
            break

    if remaining:
        tail = join_ws(remaining)
        if not lines:
            lines = [_truncate_with_ellipsis(draw, tail, font, max_width, sw)]
        else:
            merged = (lines[-1] + " " + tail).strip()
            lines[-1] = _truncate_with_ellipsis(draw, merged, font, max_width, sw)

    return lines[:max_lines] if lines else [""]


def _subtitle_chunk_durations(scene_duration: float, chunks: List[str]) -> List[float]:
    """Allocate time by chunk size so longer on-screen text gets more time (helps uploaded narration)."""
    d = max(float(scene_duration), MIN_SCENE_CLIP)
    n = len(chunks)
    if n == 0:
        return []
    if n == 1:
        return [d]
    floor_sec = SUBTITLE_MIN_CHUNK_SEC
    floor_total = n * floor_sec
    if d <= floor_total + 1e-6:
        return [d / n] * n
    remain = d - floor_total
    weights = [max(1.0, float(len(c.split()))) for c in chunks]
    tw = sum(weights)
    extras = [remain * (w / tw) for w in weights]
    out = [floor_sec + e for e in extras]
    drift = d - sum(out)
    if out:
        out[-1] = max(floor_sec * 0.5, out[-1] + drift)
    return out


def _render_subtitle_rgba_frame(
    width: int,
    height: int,
    text: str,
    style: str,
    aspect_ratio: str = "",
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
    max_lines = int(cfg.get("max_lines", 2))

    is_portrait = int(height) > int(width)
    if is_portrait:
        max_width_frac = min(0.92, max_width_frac + 0.04)
        margin_frac = max(0.068, margin_frac - 0.022)

    img = Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    base_font = max(14, int(height * font_frac))
    min_font = 13 if style == "shorts" else 12
    max_text_w = int(width * max_width_frac)

    chosen_font = _load_subtitle_font(base_font, bold=bold)
    chosen_lines: List[str] = []
    for size in range(base_font, min_font - 1, -1):
        font = _load_subtitle_font(size, bold=bold)
        lines = _wrap_subtitle_lines(text.strip(), draw, font, float(max_text_w), max_lines, stroke_w)
        lines_kept = [ln for ln in lines if ln.strip()]
        ok = bool(lines_kept) and all(
            _line_width(draw, ln, font, stroke_w) <= max_text_w + 2 for ln in lines_kept
        )
        if ok:
            chosen_font = font
            chosen_lines = lines
            break
    else:
        chosen_font = _load_subtitle_font(min_font, bold=bold)
        chosen_lines = _wrap_subtitle_lines(
            text.strip(), draw, chosen_font, float(max_text_w), max_lines, stroke_w
        )

    joined = "\n".join(chosen_lines)
    bbox = draw.multiline_textbbox(
        (0, 0), joined, font=chosen_font, spacing=4, stroke_width=stroke_w if stroke_w else 0
    )
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    box_w = min(int(width * (0.94 if not is_portrait else 0.96)), tw + 2 * pad_x)
    box_h = th + 2 * pad_y
    margin_bottom = int(height * margin_frac)
    x0 = (width - box_w) // 2
    y0 = height - margin_bottom - box_h
    y0 = min(y0, height - box_h - int(height * 0.028))
    y0 = max(0, y0)

    overlay = Image.new("RGBA", (box_w, box_h), (12, 12, 18, bg_alpha))
    img.paste(overlay, (x0, y0), overlay)

    tx = x0 + pad_x - bbox[0]
    ty = y0 + pad_y - bbox[1]
    text_kw: dict = {
        "font": chosen_font,
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
    aspect_ratio: str,
):
    chunks = _chunk_subtitle_text_for_scene(text, scene_duration, aspect_ratio, style)
    n = len(chunks)
    d = max(float(scene_duration), MIN_SCENE_CLIP)
    durations = _subtitle_chunk_durations(d, chunks)
    sub_clips = []
    for ch, each in zip(chunks, durations):
        rgba = _render_subtitle_rgba_frame(width, height, ch, style, aspect_ratio=aspect_ratio)
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
    aspect_ratio: str,
):
    ss = _normalize_subtitle_style(subtitle_style)
    if ss == "off":
        return scene_clip
    if not (scene_text or "").strip():
        return scene_clip
    d = max(float(scene_duration), MIN_SCENE_CLIP)
    try:
        strip = _build_subtitle_strip_clip(scene_text, d, width, height, ss, aspect_ratio)
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
                clip, texts[idx - 1], safe_duration, width, height, ss, aspect_ratio
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
    branding_enabled: bool = False,
    branding_logo_path: Optional[str] = None,
    branding_position: str = "bottom_right",
    branding_size: str = "medium",
    branding_opacity: float = 0.8,
):
    vd = float(video.duration)
    width = int(getattr(video, "w", 0) or getattr(video, "size", [0, 0])[0])
    height = int(getattr(video, "h", 0) or getattr(video, "size", [0, 0])[1])
    video = _apply_branding_logo(
        video,
        branding_enabled=branding_enabled,
        branding_logo_path=branding_logo_path,
        branding_position=branding_position,
        branding_size=branding_size,
        branding_opacity=branding_opacity,
        width=width,
        height=height,
        duration=vd,
    )

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


def render_scene_preview(
    *,
    image_path: str,
    output_path: str,
    scene_duration: float,
    aspect_ratio: str,
    image_fit_mode: str,
    background_music: str,
    background_music_volume: float,
    motion_effect: str,
    motion_intensity: str,
    subtitle_style: str,
    subtitle_text: str,
    full_narration_path: Optional[str],
    narration_start_sec: float,
) -> str:
    """
    Render one scene to MP4: image + motion + optional subtitles + narration slice + optional music.

    narration_start_sec is the offset in the full narration file that aligns with this scene's
    start in the multi-scene timeline (sum of prior scene durations).
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    d = max(float(scene_duration), MIN_SCENE_CLIP)
    mi = _normalize_motion_intensity(motion_intensity)
    ss = _normalize_subtitle_style(subtitle_style)
    width, height = _aspect_resolution(aspect_ratio)
    W, H = int(width), int(height)

    if not image_path or not os.path.isfile(image_path) or os.path.getsize(image_path) <= 0:
        raise RuntimeError("render_scene_preview: invalid image_path")

    base_clip = _frame_image_clip(
        image_path,
        d,
        W,
        H,
        image_fit_mode,
        motion_effect=motion_effect,
        scene_index=1,
        motion_intensity=mi,
    )
    video = _maybe_composite_subtitles(
        base_clip, subtitle_text, d, W, H, ss, aspect_ratio
    )

    narration_clip: AudioFileClip | None = None
    fp = full_narration_path
    if fp and os.path.isfile(fp) and os.path.getsize(fp) > 0:
        try:
            src = AudioFileClip(fp)
            total = float(src.duration or 0.0)
            if total > 0.05:
                t0 = max(0.0, float(narration_start_sec))
                t0 = min(t0, max(0.0, total - 0.05))
                t1 = min(t0 + d, total)
                if t1 > t0 + 0.04:
                    narration_clip = _subclip_compat(src, t0, t1)
                else:
                    try:
                        src.close()
                    except Exception:
                        pass
            else:
                try:
                    src.close()
                except Exception:
                    pass
        except Exception as exc:
            print(f"[render_scene_preview] could not load/slice narration: {exc}")
            traceback.print_exc()

    vd = max(MIN_SCENE_CLIP, float(video.duration))
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

    write_kw: dict = {"fps": 24, "codec": "libx264"}
    if final_audio is not None:
        write_kw["audio_codec"] = "aac"
    else:
        write_kw["audio"] = False

    video.write_videofile(output_path, **write_kw)

    try:
        video.close()
    except Exception:
        pass
    if final_audio is not None:
        try:
            final_audio.close()
        except Exception:
            pass
    if narration_clip is not None:
        try:
            narration_clip.close()
        except Exception:
            pass

    return output_path


def _clip_with_start(clip, start: float):
    try:
        return clip.with_start(start)
    except AttributeError:
        return clip.set_start(start)


def _apply_branding_logo(
    video_clip,
    *,
    branding_enabled: bool = False,
    branding_logo_path: Optional[str] = None,
    branding_position: str = "bottom_right",
    branding_size: str = "medium",
    branding_opacity: float = 0.8,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration: Optional[float] = None,
):
    """Composite a logo watermark onto the full video without changing resolution or duration."""
    if not branding_enabled:
        return video_clip

    fp = branding_logo_path
    if not fp or not os.path.isfile(fp) or os.path.getsize(fp) <= 0:
        print(f"[branding] logo missing or invalid at {fp!r}; skipping watermark")
        return video_clip

    w = width or int(getattr(video_clip, "w", 0) or getattr(video_clip, "size", [0, 0])[0])
    h = height or int(getattr(video_clip, "h", 0) or getattr(video_clip, "size", [0, 0])[1])
    d = float(duration if duration is not None else (video_clip.duration or 0))
    if w <= 0 or h <= 0 or d <= 0:
        print("[branding] invalid video dimensions; skipping watermark")
        return video_clip

    size_frac = {"small": 0.08, "medium": 0.12, "large": 0.16}.get(
        _normalize_branding_size(branding_size), 0.12
    )
    target_w = max(16, int(w * size_frac))
    margin_x = max(4, int(w * 0.03))
    margin_y = max(4, int(h * 0.03))
    opacity = _clamp_branding_opacity(branding_opacity)
    pos_key = _normalize_branding_position(branding_position)

    logo = None
    try:
        logo = ImageClip(fp)
        lw = float(getattr(logo, "w", 0) or 1)
        lh = float(getattr(logo, "h", 0) or 1)
        target_h = max(8, int(round(target_w * lh / max(lw, 1.0))))
        try:
            logo = logo.resized(width=target_w, height=target_h)
        except AttributeError:
            logo = logo.resize(width=target_w, height=target_h)

        try:
            logo = logo.with_duration(d)
        except AttributeError:
            logo = logo.set_duration(d)

        try:
            logo = logo.with_opacity(opacity)
        except AttributeError:
            try:
                logo = logo.set_opacity(opacity)
            except Exception:
                pass

        logo_w = int(getattr(logo, "w", target_w))
        logo_h = int(getattr(logo, "h", target_h))
        if pos_key == "top_left":
            pos = (margin_x, margin_y)
        elif pos_key == "top_right":
            pos = (w - logo_w - margin_x, margin_y)
        elif pos_key == "bottom_left":
            pos = (margin_x, h - logo_h - margin_y)
        else:
            pos = (w - logo_w - margin_x, h - logo_h - margin_y)

        try:
            logo = logo.with_position(pos)
        except AttributeError:
            logo = logo.set_position(pos)

        try:
            out = CompositeVideoClip([video_clip, logo], size=(w, h)).with_duration(d)
        except AttributeError:
            out = CompositeVideoClip([video_clip, logo], size=(w, h)).set_duration(d)
        return out
    except Exception as exc:
        print(f"[branding] failed to apply logo watermark: {exc!r}")
        traceback.print_exc()
        if logo is not None:
            try:
                logo.close()
            except Exception:
                pass
        return video_clip


def render_subtitles_on_video(
    *,
    video_path: str,
    output_path: str,
    subtitles: List[dict],
    subtitle_style: str,
    branding_enabled: bool = False,
    branding_logo_path: Optional[str] = None,
    branding_position: str = "bottom_right",
    branding_size: str = "medium",
    branding_opacity: float = 0.8,
) -> str:
    """Burn manually timed subtitles onto an existing video without changing visuals."""
    if not video_path or not os.path.isfile(video_path) or os.path.getsize(video_path) <= 0:
        raise RuntimeError("render_subtitles_on_video: invalid video_path")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    base = VideoFileClip(video_path)
    overlays = []
    final = base
    try:
        width = int(getattr(base, "w", 0) or getattr(base, "size", [0, 0])[0])
        height = int(getattr(base, "h", 0) or getattr(base, "size", [0, 0])[1])
        if width <= 0 or height <= 0:
            raise RuntimeError("render_subtitles_on_video: could not determine video size")

        duration = float(base.duration or 0.0)
        if duration <= 0:
            raise RuntimeError("render_subtitles_on_video: source video has no duration")

        ss = _normalize_subtitle_style(subtitle_style)
        aspect_hint = "9:16" if height > width else "16:9"

        if ss != "off":
            for item in subtitles:
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                start = max(0.0, float(item.get("start_seconds") or 0.0))
                end = min(duration, float(item.get("end_seconds") or 0.0))
                if end <= start + 0.04:
                    continue
                rgba = _render_subtitle_rgba_frame(width, height, text, ss, aspect_ratio=aspect_hint)
                overlay = _imageclip_from_rgba(rgba, end - start)
                overlays.append(_clip_with_start(overlay, start))

        if overlays:
            try:
                final = CompositeVideoClip([base, *overlays], size=(width, height)).with_duration(duration)
            except AttributeError:
                final = CompositeVideoClip([base, *overlays], size=(width, height)).set_duration(duration)

        final = _apply_branding_logo(
            final,
            branding_enabled=branding_enabled,
            branding_logo_path=branding_logo_path,
            branding_position=branding_position,
            branding_size=branding_size,
            branding_opacity=branding_opacity,
            width=width,
            height=height,
            duration=duration,
        )

        write_kw: dict = {"fps": getattr(base, "fps", None) or 24, "codec": "libx264"}
        if getattr(base, "audio", None) is not None:
            write_kw["audio_codec"] = "aac"
        else:
            write_kw["audio"] = False
        final.write_videofile(output_path, **write_kw)
        return output_path
    finally:
        for clip in overlays:
            try:
                clip.close()
            except Exception:
                pass
        if final is not base:
            try:
                final.close()
            except Exception:
                pass
        try:
            base.close()
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
    branding_enabled: bool = False,
    branding_logo_path: Optional[str] = None,
    branding_position: str = "bottom_right",
    branding_size: str = "medium",
    branding_opacity: float = 0.8,
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
            branding_enabled=branding_enabled,
            branding_logo_path=branding_logo_path,
            branding_position=branding_position,
            branding_size=branding_size,
            branding_opacity=branding_opacity,
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
                pad_clip, st_list[-1], pad, width, height, ss, aspect_ratio
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
        branding_enabled=branding_enabled,
        branding_logo_path=branding_logo_path,
        branding_position=branding_position,
        branding_size=branding_size,
        branding_opacity=branding_opacity,
    )
    return output_path
