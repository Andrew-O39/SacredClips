"""
Filesystem paths under BASE_OUTPUT_DIR: normalize for portable persistence
and expand for backward-compatible API responses.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .. import config

FILESYSTEM_PATH_KEYS = frozenset(
    {
        "video_path",
        "source_video_path",
        "narration_audio_path",
        "branding_logo_path",
        "preview_video_path",
        "image_path",
    }
)


def base_output_root() -> Path:
    return Path(config.BASE_OUTPUT_DIR).resolve()


def to_output_relative(path: str | Path) -> str:
    """
    Convert a path under BASE_OUTPUT_DIR into a normalized POSIX-style relative path.
    Raise ValueError if the path is outside BASE_OUTPUT_DIR.
    """
    root = base_output_root()
    raw = Path(path).expanduser()
    if raw.is_absolute():
        resolved = raw.resolve()
    else:
        if any(part == ".." for part in raw.parts):
            raise ValueError(f"Path traversal not allowed: {path}")
        resolved = (root / raw).resolve()
    try:
        rel = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path is outside BASE_OUTPUT_DIR: {path}") from exc
    if any(part == ".." for part in rel.parts):
        raise ValueError(f"Path traversal not allowed: {path}")
    return rel.as_posix()


def try_to_output_relative(path: str | Path) -> str | None:
    try:
        return to_output_relative(path)
    except ValueError:
        return None


def from_output_relative(path: str | Path) -> Path:
    """
    Resolve a relative output path safely under BASE_OUTPUT_DIR.
    Reject traversal and paths outside BASE_OUTPUT_DIR.
    """
    root = base_output_root()
    raw = Path(path).expanduser()
    if any(part == ".." for part in raw.parts):
        raise ValueError(f"Path traversal not allowed: {path}")
    if raw.is_absolute():
        resolved = raw.resolve()
    else:
        resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path is outside BASE_OUTPUT_DIR: {path}") from exc
    return resolved


def try_from_output_relative(path: str | Path) -> Path | None:
    try:
        return from_output_relative(path)
    except ValueError:
        return None


def _normalize_path_value(value: str, *, strict: bool) -> tuple[str | None, bool]:
    rel = try_to_output_relative(value)
    if rel is not None:
        changed = rel != value
        return rel, changed
    if strict:
        raise ValueError(f"Cannot normalize path under BASE_OUTPUT_DIR: {value}")
    return None, value is not None


def _expand_path_value(value: str) -> tuple[str | None, bool]:
    if not value:
        return value, False
    p = Path(value).expanduser()
    if p.is_absolute():
        return value, False
    resolved = try_from_output_relative(value)
    if resolved is None:
        return None, True
    return str(resolved), True


def normalize_result_for_persist(result: Any, *, strict: bool = True) -> tuple[Any, bool]:
    """
    Recursively convert filesystem path fields to BASE_OUTPUT_DIR-relative strings.
    URL fields (video_url, image_url, etc.) are left unchanged.
    """
    if result is None:
        return result, False
    if isinstance(result, dict):
        changed = False
        out: dict[str, Any] = {}
        for key, val in result.items():
            if key in FILESYSTEM_PATH_KEYS and isinstance(val, str):
                new_val, key_changed = _normalize_path_value(val, strict=strict)
                out[key] = new_val
                changed = changed or key_changed or (new_val != val)
            elif key == "scenes" and isinstance(val, list):
                new_scenes, scenes_changed = _normalize_scenes(val, strict=strict)
                out[key] = new_scenes
                changed = changed or scenes_changed
            elif isinstance(val, (dict, list)):
                new_val, nested_changed = normalize_result_for_persist(val, strict=strict)
                out[key] = new_val
                changed = changed or nested_changed
            else:
                out[key] = val
        return out, changed
    if isinstance(result, list):
        changed = False
        out_list: list[Any] = []
        for item in result:
            new_item, item_changed = normalize_result_for_persist(item, strict=strict)
            out_list.append(new_item)
            changed = changed or item_changed
        return out_list, changed
    return result, False


def _normalize_scenes(scenes: list[Any], *, strict: bool) -> tuple[list[Any], bool]:
    changed = False
    out: list[Any] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            out.append(scene)
            continue
        scene_out = dict(scene)
        ip = scene.get("image_path")
        if isinstance(ip, str):
            new_ip, ip_changed = _normalize_path_value(ip, strict=strict)
            scene_out["image_path"] = new_ip
            changed = changed or ip_changed or (new_ip != ip)
        out.append(scene_out)
    return out, changed


def expand_result_for_api(result: Any) -> Any:
    """Expand relative filesystem paths to absolute for API consumers."""
    if result is None:
        return None
    if isinstance(result, dict):
        out: dict[str, Any] = {}
        for key, val in result.items():
            if key in FILESYSTEM_PATH_KEYS and isinstance(val, str):
                expanded, _ = _expand_path_value(val)
                out[key] = expanded
            elif key == "scenes" and isinstance(val, list):
                out[key] = _expand_scenes(val)
            elif isinstance(val, (dict, list)):
                out[key] = expand_result_for_api(val)
            else:
                out[key] = val
        return out
    if isinstance(result, list):
        return [expand_result_for_api(item) for item in result]
    return result


def _expand_scenes(scenes: list[Any]) -> list[Any]:
    out: list[Any] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            out.append(scene)
            continue
        scene_out = dict(scene)
        ip = scene.get("image_path")
        if isinstance(ip, str):
            expanded, _ = _expand_path_value(ip)
            scene_out["image_path"] = expanded
        out.append(scene_out)
    return out


def expand_job_for_api(job: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a job record with result paths expanded for API responses."""
    out = copy.deepcopy(job)
    if out.get("result") is not None:
        out["result"] = expand_result_for_api(out["result"])
    return out
