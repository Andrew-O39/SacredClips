import base64
import os
from pathlib import Path
from typing import List

from .. import config

try:
    from openai import OpenAI  # type: ignore
except ImportError:
    OpenAI = None  # type: ignore


def _make_single_placeholder_image(
    topic: str,
    keywords: List[str],
    scene_index: int,
    path: Path,
) -> str:
    """
    Create a single placeholder image for one scene using Pillow.
    The file is always written to the given `path`.
    """
    from PIL import Image, ImageDraw  # pillow is in requirements

    os.makedirs(path.parent, exist_ok=True)

    # Slightly vary the background per scene so they don't look identical
    base_color = 40 + (scene_index * 15) % 80
    img = Image.new("RGB", (1080, 1920), color=(base_color, base_color, 90))
    draw = ImageDraw.Draw(img)

    # Build some readable multiline text.
    lines = [f"Scene {scene_index}", topic]
    if keywords:
        lines.append(", ".join(keywords))

    text = "\n".join(lines)
    # Draw text near the top-left; Pillow default font is small, but fine for a placeholder
    draw.multiline_text((50, 80), text, fill=(255, 255, 255), spacing=6)

    img.save(path)
    return str(path)


def generate_images_for_keywords(
    topic: str,
    per_scene_keywords: List[List[str]],
    output_dir: str,
) -> List[str]:
    """
    Generate one image per scene.

    - If OpenAI images are available and succeed, use them.
    - If OpenAI fails for a scene (or is not available at all), create a
      placeholder PNG for that *specific* scene index.

    This ensures you always get N images for N scenes, and they are saved as:
      scene_1.png, scene_2.png, ...
    """
    os.makedirs(output_dir, exist_ok=True)

    image_paths: List[str] = []

    use_openai = bool(config.OPENAI_API_KEY and OpenAI is not None)
    client = OpenAI(api_key=config.OPENAI_API_KEY) if use_openai else None

    for idx, keywords in enumerate(per_scene_keywords, start=1):
        img_path = Path(output_dir) / f"scene_{idx}.png"

        # If we can't or shouldn't use OpenAI at all, go straight to placeholder
        if not use_openai:
            print(f"[image_service] No OPENAI_API_KEY or OpenAI library; using placeholder for scene {idx}.")
            image_paths.append(
                _make_single_placeholder_image(topic, keywords, idx, img_path)
            )
            continue

        prompt = (
            f"Vertical 9:16 illustration for a short educational video about the religious topic '{topic}'. "
            f"Focus on: {', '.join(keywords)}. "
            "Style should be neutral, calm, and respectful. Avoid depicting specific religious figures unless "
            "explicitly requested and appropriate. No visible text in the image."
        )

        try:
            # IMPORTANT: size must be one of: "1024x1024", "1024x1536", "1536x1024", or "auto"
            # We'll use a vertical-friendly "1024x1536".
            result = client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size="1024x1536",
            )

            img_b64 = result.data[0].b64_json
            img_bytes = base64.b64decode(img_b64)

            with open(img_path, "wb") as f:
                f.write(img_bytes)

            image_paths.append(str(img_path))

        except Exception as e:
            # If anything goes wrong for this scene, fall back to a placeholder *for this scene only*
            print(f"[image_service] OpenAI image error for scene {idx}, using placeholder: {e}")
            image_paths.append(
                _make_single_placeholder_image(topic, keywords, idx, img_path)
            )

    return image_paths