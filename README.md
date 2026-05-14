# SacredClips

**SacredClips** is a local, single-user web app that turns **religious or spiritual topics** into short **educational explainer videos** with optional **AI script, narration, and images**, or a **manual** workflow with your own script, narration, and images.

Output is suitable for **YouTube**, **Instagram Reels**, **TikTok-style vertical video**, or **horizontal** formats, depending on settings.

The product aims for **neutral, respectful, educational** tone—not persuasion or political messaging. **Always review AI-generated content** before publishing.

---

## What it does

| Area | Capabilities |
|------|----------------|
| **AI mode** | Topic → script → scenes → OpenAI TTS narration → AI images per scene → rendered MP4. Visual styles, regeneration from edited script/scenes. |
| **Manual mode** | Your script, per-scene text; **uploaded or TTS narration**; per scene **uploaded image**, **AI-generated image**, or **placeholder**; timing assistant; full control of durations. |
| **Formats** | **16:9**, **9:16** (shorts/reels), **1:1**; **fit** vs **fill** image framing. |
| **Polish** | Optional **background music** and volume; **motion** (none, gentle zoom, slow pan, Ken Burns) and **intensity**; **subtitles** (off, minimal, cinematic, shorts). |
| **Editing** | Horizontal **scene timeline** after generation: reorder, edit text/keywords/duration, **add / duplicate / remove** scenes, **replace** manual scene images, regenerate. |
| **Publishing** | **YouTube upload** via Google OAuth (local token file). |

**Uploaded narration and subtitles:** Subtitles are derived from **scene text** and **scene timing**. They track scene boundaries, not word-level speech. For best results with uploaded audio, prefer **shorter scene text** and **more scene cuts** where the spoken content changes (see `USER_GUIDE.md`).

---

## AI mode vs manual mode

- **AI mode:** Enter topic, style, duration, and options → one pipeline produces script, narration, images, and video. Afterward you can edit the script or scene cards and **regenerate**.
- **Manual mode:** Paste or build a script, split into scenes, set image source per scene (upload / generate / placeholder), choose TTS or **uploaded narration**, then generate. Afterward the same **scene editor** and regeneration options apply.

---

## Quick start

1. **Install FFmpeg** (required for MoviePy). Example: `brew install ffmpeg` (macOS) or your OS package manager.
2. **Python backend** (from project root):

   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```

   API: `http://127.0.0.1:8000` — interactive docs: `http://127.0.0.1:8000/docs`

3. **Frontend** (separate terminal):

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   UI: `http://127.0.0.1:5173` — expects backend at `http://localhost:8000` (see `API_BASE_URL` in `frontend/src/App.tsx` if you change ports).

4. Open the UI, choose **AI** or **Manual**, configure topic/script and options, then generate.

For step-by-step usage, see **`USER_GUIDE.md`**. For API, data flow, and implementation notes, see **`TECHNICAL_GUIDE.md`**.

---

## Setup and environment variables

Create a **`.env`** file in the project root (loaded by `app/config.py`):

```env
# OpenAI (script, TTS, images when available)
OPENAI_API_KEY=your_key_here

# Generated media root (default: outputs)
BASE_OUTPUT_DIR=outputs

# YouTube OAuth (optional)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/youtube/callback

# Optional overrides
YOUTUBE_TOKEN_PATH=outputs/youtube_tokens.json
YOUTUBE_UPLOAD_DEFAULT_PRIVACY=unlisted
```

### OpenAI usage and billing

Script, image, and TTS calls use your **OpenAI account** and are subject to **OpenAI pricing and quotas**. If the key is missing or requests fail, the app falls back to **placeholder images** and **empty placeholder audio files** where applicable so the pipeline can still be tested locally.

### Background music

Bundled royalty-free tracks live under `assets/music/` in the repo. The backend serves previews from `/assets/music/…` and mixes selected tracks during render when background music is not `none`. Ensure those files remain present if you rely on music in production.

---

## Project layout

```text
SacredClips/
├── app/                    # FastAPI backend
│   ├── main.py             # Routes, media mounts, manual multipart handling
│   ├── config.py           # Env and paths
│   ├── schemas.py          # Pydantic models (requests/responses)
│   └── services/           # script, TTS, image, video, YouTube
├── assets/music/           # Bundled background music files
├── frontend/               # Vite + React + TypeScript
├── outputs/                # Default BASE_OUTPUT_DIR (topic subfolders + tokens)
├── requirements.txt
├── README.md
├── USER_GUIDE.md
└── TECHNICAL_GUIDE.md
```

---

## Screenshots

_Add your own screenshots here (e.g. main form, scene editor, preview, YouTube panel)._  

---

## Customization (where to change behavior)

| Concern | Primary files |
|---------|----------------|
| Script / scenes | `app/services/script_service.py` |
| TTS | `app/services/tts_service.py` |
| Images | `app/services/image_service.py` |
| Render, subtitles, motion, music mix | `app/services/video_service.py` |
| YouTube OAuth / upload | `app/services/youtube_service.py`, `app/main.py` |
| UI flows | `frontend/src/App.tsx` |

---

## Safety and responsibility

Generated material is **assistive**, not authoritative. Verify facts and tone before publishing, especially for sensitive religious topics.

---

## License

Use responsibly; review all generated content before public release.
