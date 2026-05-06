import base64
import os
import textwrap
from pathlib import Path
from typing import List, Optional

from .. import config

try:
    from openai import OpenAI  # type: ignore
except ImportError:
    OpenAI = None  # type: ignore

# Default and allowed visual styles (must match frontend options)
DEFAULT_VISUAL_STYLE = "Classical sacred art"
DEFAULT_ASPECT_RATIO = "16:9"

ASPECT_IMAGE_SIZE: dict[str, str] = {
    "9:16": "1024x1536",
    "16:9": "1536x1024",
    "1:1": "1024x1024",
}

ASPECT_IMAGE_LABEL: dict[str, str] = {
    "9:16": "vertical 9:16",
    "16:9": "horizontal 16:9",
    "1:1": "square 1:1",
}

STYLE_PROMPT_BLOCKS: dict[str, str] = {
    "Classical sacred art": (
        "Visual treatment: classical sacred art — rich oil-painting feel inspired by European religious "
        "panel painting and manuscript illumination. "
        "Painterly brushwork, subtle glaze, gold leaf hints where tasteful, balanced composition, "
        "timeless and reverent. "
        "Atmosphere: historical or medieval when it fits the topic; calm, contemplative, church or study mood."
    ),
    "Cinematic realism": (
        "Visual treatment: cinematic realism — photoreal documentary still, film-quality depth of field, "
        "natural textures, restrained color grading. "
        "Soft cinematic light (no harsh blockbuster contrast); grounded, solemn, respectful. "
        "Feels like a quiet observational documentary about faith and heritage, not a fantasy film."
    ),
    "Historical documentary": (
        "Visual treatment: historical documentary illustration — academically grounded, evocative of museum "
        "exhibits and archival photography interpretation. "
        "Muted earthy palette, clear sense of period architecture, artifacts, manuscripts, textiles, "
        "or pilgrimage landscapes without sensationalism."
    ),
    "Warm candlelit painting": (
        "Visual treatment: warm candlelit painting — interior or twilight ambience with glowing candle flames, "
        "soft warm key light and gentle shadows, subtle chiaroscuro. "
        "Painterly but realistic; intimate, reflective, devotional mood without melodrama."
    ),
    "Minimal reverent illustration": (
        "Visual treatment: minimal reverent illustration — simplified forms, restrained palette, ample negative "
        "space, clean composition akin to respectful editorial illustration. "
        "Symbolic objects, architecture silhouettes, or abstracted natural elements; understated and calm."
    ),
}

NEGATIVE_GUIDANCE = (
    "Avoid: cartoon, anime, caricature, chibi, or stylized mascot looks; fantasy creatures, dragons, glowing "
    "magic, or exaggerated Hollywood/action drama; meme aesthetics; cluttered neon or sci-fi visuals. "
    "Avoid modern objects (phones, cars, LEDs) unless the topic explicitly calls for contemporary context. "
    "No visible text, captions, typography, logos, watermarks, or lettering in the image. "
    "Avoid distorted anatomy, duplicated limbs, or grotesque faces; keep human forms subtle and graceful if "
    "any appear."
)

RESPECT_AND_SAFETY = (
    "Content guidance: respectful, inclusive educational imagery about religion or spirituality. "
    "Prefer symbolic motifs, sacred architecture, liturgical objects (candles, vessels, manuscripts), "
    "landscapes, or generic contemplative figures from behind or at a distance—not identifiable portraits "
    "of revered prophets, deities, or holy persons, and nothing sensational or mocking. "
    "Keep imagery calm, grounded, and appropriate for interfaith classrooms."
)


def resolve_visual_style_label(visual_style: str) -> str:
    name = (visual_style or "").strip()
    if name in STYLE_PROMPT_BLOCKS:
        return name
    return DEFAULT_VISUAL_STYLE


def build_image_prompt(
    topic: str,
    keywords: List[str],
    scene_index: int,
    visual_style: str = DEFAULT_VISUAL_STYLE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    scene_text: Optional[str] = None,
) -> str:
    """
    Build a single OpenAI Images prompt combining topic, optional scene narration,
    keywords, chosen visual style block, negatives, and respect guardrails.
    """
    resolved_style = resolve_visual_style_label(visual_style)
    style_block = STYLE_PROMPT_BLOCKS[resolved_style]

    kw_part = ", ".join(kw.strip() for kw in keywords if kw.strip()) if keywords else "(no extra keywords)"

    scene_part = ""
    if scene_text and scene_text.strip():
        excerpt = scene_text.strip()
        if len(excerpt) > 600:
            excerpt = excerpt[:597] + "..."
        scene_part = f" Narration context for this moment (describe mood and setting, do not paint text): {excerpt}"

    orientation = ASPECT_IMAGE_LABEL.get(aspect_ratio, ASPECT_IMAGE_LABEL[DEFAULT_ASPECT_RATIO])

    return (
        f"{orientation.capitalize()} image for scene {scene_index} of an educational video about: '{topic}'. "
        f"Mood & subject cues: {kw_part}.{scene_part} "
        f"{style_block} "
        f"Lighting: soft, warm, natural or candlelit where fitting; gentle shadows; contemplative air. "
        f"Overall: realistic or painterly-realistic, reverent, calm, reflective—not flashy or theatrical. "
        f"{RESPECT_AND_SAFETY} "
        f"{NEGATIVE_GUIDANCE}"
    )


def _make_single_placeholder_image(
    topic: str,
    keywords: List[str],
    scene_index: int,
    visual_style: str,
    aspect_ratio: str,
    path: Path,
    scene_text: Optional[str] = None,
) -> str:
    """
    Create a single placeholder image for one scene using Pillow.
    The file is always written to the given `path`.
    """
    from PIL import Image, ImageDraw  # pillow is in requirements

    os.makedirs(path.parent, exist_ok=True)

    base_color = 40 + (scene_index * 15) % 80
    if aspect_ratio == "9:16":
        size = (1080, 1920)
    elif aspect_ratio == "1:1":
        size = (1080, 1080)
    else:
        size = (1920, 1080)
    img = Image.new("RGB", size, color=(base_color, base_color, 90))
    draw = ImageDraw.Draw(img)

    resolved = resolve_visual_style_label(visual_style)
    lines: List[str] = [
        f"Scene {scene_index}",
        f"Topic: {topic}",
        f"Aspect ratio: {aspect_ratio}",
        f"Visual style: {resolved}",
    ]
    if keywords:
        kw_line = ", ".join(keywords)
        if len(kw_line) > 200:
            kw_line = kw_line[:197] + "..."
        lines.append(f"Keywords: {kw_line}")
    if scene_text and scene_text.strip():
        excerpt = scene_text.strip().replace("\n", " ")
        if len(excerpt) > 160:
            excerpt = excerpt[:157] + "..."
        lines.append(f"Scene text: {excerpt}")
    lines.append("(Placeholder — OpenAI image unavailable)")

    wrapped_lines: List[str] = []
    for line in lines:
        if len(line) <= 44:
            wrapped_lines.append(line)
        else:
            wrapped_lines.extend(
                textwrap.wrap(line, width=44, break_long_words=True, replace_whitespace=False)
            )
    text = "\n".join(wrapped_lines)
    draw.multiline_text((50, 80), text, fill=(255, 255, 255), spacing=8)

    img.save(path)
    return str(path)


def write_placeholder_scene_image(
    topic: str,
    keywords: List[str],
    scene_index: int,
    visual_style: str,
    aspect_ratio: str,
    output_path: str,
    scene_text: Optional[str] = None,
) -> str:
    """
    Write one placeholder PNG for a scene at the given filesystem path (for manual uploads / fallbacks).
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    resolved = resolve_visual_style_label(visual_style)
    return _make_single_placeholder_image(
        topic,
        keywords,
        scene_index,
        resolved,
        aspect_ratio,
        Path(output_path),
        scene_text=scene_text,
    )


def generate_images_for_keywords(
    topic: str,
    per_scene_keywords: List[List[str]],
    output_dir: str,
    visual_style: str = DEFAULT_VISUAL_STYLE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    scene_texts: Optional[List[str]] = None,
) -> List[str]:
    """
    Generate one image per scene.

    - If OpenAI images are available and succeed, use them.
    - If OpenAI fails for a scene (or is not available at all), create a
      placeholder PNG for that *specific* scene index.

    scene_texts, when provided, must align with per_scene_keywords by index
    (same length as number of scenes); shorter lists are padded with None.
    """
    os.makedirs(output_dir, exist_ok=True)

    image_paths: List[str] = []
    resolved_style = resolve_visual_style_label(visual_style)

    n = len(per_scene_keywords)
    texts: List[Optional[str]] = [None] * n
    if scene_texts:
        for i in range(min(n, len(scene_texts))):
            texts[i] = scene_texts[i]

    use_openai = bool(config.OPENAI_API_KEY and OpenAI is not None)
    client = OpenAI(api_key=config.OPENAI_API_KEY) if use_openai else None

    for idx, keywords in enumerate(per_scene_keywords, start=1):
        img_path = Path(output_dir) / f"scene_{idx}.png"
        scene_text = texts[idx - 1] if idx - 1 < len(texts) else None

        if not use_openai:
            print(
                f"[image_service] No OPENAI_API_KEY or OpenAI library; "
                f"using placeholder for scene {idx} (style={resolved_style})."
            )
            image_paths.append(
                _make_single_placeholder_image(
                    topic, keywords, idx, resolved_style, aspect_ratio, img_path, scene_text=scene_text
                )
            )
            continue

        prompt = build_image_prompt(
            topic=topic,
            keywords=keywords,
            scene_index=idx,
            visual_style=resolved_style,
            aspect_ratio=aspect_ratio,
            scene_text=scene_text,
        )

        try:
            size = ASPECT_IMAGE_SIZE.get(aspect_ratio, ASPECT_IMAGE_SIZE[DEFAULT_ASPECT_RATIO])
            result = client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size=size,
            )

            img_b64 = result.data[0].b64_json
            img_bytes = base64.b64decode(img_b64)

            with open(img_path, "wb") as f:
                f.write(img_bytes)

            image_paths.append(str(img_path))

        except Exception as e:
            print(f"[image_service] OpenAI image error for scene {idx}, using placeholder: {e}")
            image_paths.append(
                _make_single_placeholder_image(
                    topic, keywords, idx, resolved_style, aspect_ratio, img_path, scene_text=scene_text
                )
            )

    return image_paths
