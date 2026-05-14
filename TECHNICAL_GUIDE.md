# SacredClips Technical Guide

This document is for **developers** maintaining or extending SacredClips. End-user steps are in **`USER_GUIDE.md`**.

---

## 1. Architecture overview

| Layer | Stack | Role |
|-------|--------|------|
| **Frontend** | Vite, React, TypeScript (`frontend/src/App.tsx`) | Forms, scene timeline, preview, YouTube UI; calls FastAPI via `fetch`. |
| **Backend** | FastAPI (`app/main.py`) | REST API, static serving of rendered media and bundled assets. |
| **Services** | `app/services/*` | Script, TTS, images, **MoviePy** render, YouTube OAuth/upload. |
| **Config** | `app/config.py`, `.env` | `OPENAI_API_KEY`, `BASE_OUTPUT_DIR`, Google/YouTube settings. |

**Deployment model:** Single-user, **local** filesystem under `BASE_OUTPUT_DIR` (default `outputs/`). **No database**; persistence of “which file to reuse” for regeneration is carried in **API responses** and **client state** (`image_path`, `image_mode`, `narration_audio_path`, etc.), not in a separate store.

**CORS:** `app/main.py` allows `localhost:5173` and `127.0.0.1:5173` for the Vite dev server.

---

## 2. Repository layout

```text
app/
  main.py           # FastAPI app, routes, multipart manual-video, media mounts
  config.py         # Environment-driven settings
  schemas.py        # Pydantic models: VideoRequest, ManualVideoRequest, Scene, VideoResponse, …
  services/
    script_service.py
    tts_service.py
    image_service.py
    video_service.py
    youtube_service.py
frontend/src/App.tsx   # Monolithic UI + API client
assets/music/          # Bundled MP3s for background music
```

Static mounts in `main.py`:

- **`/media`** → `BASE_OUTPUT_DIR` resolved (generated topic trees).
- **`/assets`** → project `assets/` (e.g. music previews).

---

## 3. HTTP API (key routes)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness. |
| `POST` | `/generate-video` | **AI pipeline:** `VideoRequest` JSON → script + scenes + TTS + images + render. |
| `POST` | `/generate-video-from-scenes` | **Regeneration:** `ManualVideoRequest` JSON — edited `script_text` + `scenes`; reuses uploads when client sends `image_mode` / `image_path` and optional narration fields. |
| `POST` | `/generate-video-from-script` | Same handler stack as **from-scenes** (shared implementation); kept for API parity. The **frontend** currently uses **from-scenes** for JSON regeneration. |
| `POST` | `/manual-video` | **Multipart** manual create or **multipart regeneration** when new image files are present. Form fields + per-scene `scene_upload_{index}` / `scene_image_mode_{index}`. |
| `GET` | `/auth/youtube/start` | Returns Google OAuth URL. |
| `GET` | `/auth/youtube/callback` | OAuth redirect handler; exchanges code for tokens. |
| `GET` | `/auth/youtube/status` | Whether tokens exist / connection implied. |
| `POST` | `/publish/youtube` | Upload a rendered file (client sends server `video_path`). |

Interactive OpenAPI: `/docs`.

**Note:** The JSON regeneration endpoints (`/generate-video-from-scenes` and `/generate-video-from-script`) currently pass `used_ai_flag=False` into `_finalize_video_response`, so `VideoResponse.used_ai` is **false** in that response even when images were AI-regenerated. The frontend uses this flag for copy (e.g. manual vs AI hints); adjust in `main.py` if you need the flag to track “any AI images in this render.”

---

## 4. Data models (concise)

### `VideoRequest` (AI generation)

Topic, style, duration, `visual_style`, `aspect_ratio`, `image_fit_mode`, `background_music`, `background_music_volume`, `motion_effect`, `motion_intensity`, `subtitle_style`.

### `Scene`

- `index` (≥ 1), `text`, `keywords`, `duration_seconds`
- Optional: `image_url` (server-populated URL under `/media/...`)
- Optional persistence: `image_mode` (`upload` | `generate` | `placeholder`), `image_path` (absolute path under topic output when returned)

### `ManualVideoRequest` (JSON regeneration)

Same high-level options as manual flow plus `script_text`, `scenes[]`, optional `narration_source`, `narration_audio_path`.

### `VideoResponse`

`video_path`, `video_url`, `script_text`, `scenes[]`, `used_ai`, optional `narration_source` / `narration_audio_path` for client persistence.

---

## 5. Output directory structure

`media_root = Path(BASE_OUTPUT_DIR).resolve()` (see `main.py`).

For each **slugified topic**:

```text
<media_root>/<topic_slug>/audio/
<media_root>/<topic_slug>/images/
<media_root>/<topic_slug>/videos/final_video.mp4
```

Slug rules: see `_slugify` in `main.py` (sanitized filesystem-safe segment, length-capped).

YouTube token file default: `YOUTUBE_TOKEN_PATH` (often `outputs/youtube_tokens.json`).

---

## 6. Asset persistence and regeneration

### JSON path (`_regenerate_from_manual_request`)

- For each scene (sorted by `index`), `image_mode` + `image_path` determine behavior:
  - **`upload`** with a path that resolves under the topic **`images/`** directory → **reuse file** (path traversal rejected).
  - **`placeholder`** → write a new placeholder image for that scene index.
  - **`generate`** (or invalid upload) → AI image into a regen-specific subdirectory, or placeholder on failure.
- **Narration:** If `narration_source == upload` and `narration_audio_path` resolves under topic **`audio/`**, reuse; else **TTS** from `script_text` and response reflects `tts` + no path.

### Multipart path (`manual_video`)

- **Scenes** come from `scenes_json` (stripped of client `image_url` on parse).
- Per scene: `scene_image_mode_{n}` and optional `scene_upload_{n}`.
- If mode is **`upload`** but **no new file** is posted, the server **reuses** `image_path` from the parsed scene when it is safe under `images_dir` (post-regeneration workflow without re-uploading every asset).
- **Narration:** If `narration_source == upload` and a file is posted, it is saved under `audio/`. If no file but **`narration_audio_path`** is posted and safe under `audio_dir`, that file is **reused** (replacement-image regeneration without re-uploading narration).

### Path safety

`_safe_resolved_file_under_dir(expected_parent, candidate)` resolves `candidate` and requires it to live under `expected_parent` after resolution, and be a non-empty file.

---

## 7. Video rendering (`video_service.py`)

### Scene clips

- `_clips_from_images` loads each image into a sized clip (`_frame_image_clip`) with **fit** or **fill**, then applies **motion** via `_apply_motion_to_clip` (MoviePy **transform** or composite patterns depending on effect).
- **Subtitles:** `_maybe_composite_subtitles` composites a transparent PNG strip per scene when style ≠ `off`.

### Subtitle chunking (high level)

- Text is split into **time-sequential chunks** per scene; each chunk gets a sub-clip of the scene duration.
- **Weighted durations:** After a per-scene minimum, remaining scene time is allocated by **chunk weight** (e.g. word count) so longer phrases get more time than very short ones (helps **uploaded narration** where wall clock is not tied to sentence boundaries).
- **Shorts / 9:16:** Finer splitting (commas/semicolons/colons, shorter character budget per chunk, more chunk slots). **Shorts** overlay style allows up to **three** lines; others typically **two**.
- **Rendering:** PIL draws RGBA overlays; font size steps down until lines fit within max width; ellipsis is a **last resort**. Portrait frames widen the usable subtitle band slightly in code paths that detect tall frames.

**Not implemented:** Whisper / transcription, word-level karaoke, per-word timeline editing in the UI.

### Motion

- **gentle_zoom:** per-frame scale + center crop via transform.
- **slow_pan / ken_burns:** resize canvas + position functions with eased progress (`_motion_progress_eased`, smoothstep).

### Audio

- Narration loaded with MoviePy **`AudioFileClip`** when valid non-empty file exists.
- Scene durations may be **scaled to narration length** when narration is usable (`_scale_scene_durations_to_target`).
- **Background music:** optional looped/faded music clip, mixed with **`CompositeAudioClip`** when both narration and music exist (`_compose_final_audio`).

---

## 8. OpenAI integrations

- **Script:** `script_service.generate_script` returns `(script_text, scenes, used_ai)`. With a valid OpenAI client and key it calls the model; otherwise (or on failure) it uses `_build_fallback_script`, which emits deterministic template scenes and sets `used_ai` to **false**.
- **TTS:** `tts_service.text_to_speech` uses **`gpt-4o-mini-tts`** / **`alloy`** when the SDK call succeeds; on failure or missing key, writes an **empty placeholder file** (render pipeline treats empty audio as unusable in places—see `render_video` guards).
- **Images:** `image_service` requests images from OpenAI when configured; otherwise Pillow-based placeholders.

Exact models and prompts belong in the respective service files; keep docs aligned when you change them.

---

## 9. Frontend regeneration routing

Implemented in `App.tsx` (conceptually):

1. If **manual** result (`!used_ai`) and **any** `replacementUploads` entry has a `File`, build **`FormData`** for `/manual-video` (scenes JSON + globals + per-scene modes/uploads + narration reuse fields).
2. Else build **`ManualVideoRequest`-shaped JSON** for `/generate-video-from-scenes` (includes `scenesForApiPayload` with `image_mode` / `image_path`, optional narration fields).

Scene list edits (**add / duplicate / remove / move**) clear replacement file state to avoid index drift.

---

## 10. YouTube

`youtube_service` handles OAuth state, token storage on disk, resumable upload API usage. Callback HTML in `main.py` posts a message back to the opener window for the dev origin.

---

## 11. Dependencies and runtime

- **Python:** FastAPI, Pydantic, Pillow, MoviePy, numpy, OpenAI SDK, Google API clients as per `requirements.txt`.
- **FFmpeg:** Required on the host for MoviePy encoding.
- **Node:** Vite 5 + React for the UI.

---

## 12. Implementation constraints (intentional)

- **Single-user / local:** No multi-tenant isolation in code paths reviewed here.
- **No cloud asset store:** All paths are local under `BASE_OUTPUT_DIR`.
- **Security:** Path reuse checks prevent `..` style escapes from accepted `image_path` / `narration_audio_path` values; multipart uploads are written only under the prepared topic directories.

When extending the app, preserve these assumptions or update both code and documentation together.
