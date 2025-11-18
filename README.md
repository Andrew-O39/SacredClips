
# SacredClips – AI Religious Video Generator

**SacredClips** is a small full‑stack app that turns a religious or spiritual topic
into a short vertical explainer video, ready for TikTok / Reels / Shorts.

It focuses **only on religious/spiritual topics**, and aims to be **neutral, respectful,
and educational** – not persuasive or political.


## Project structure

```text
ai_video_generator_full/
│
├─ app/                 # FastAPI backend
│  ├─ main.py           # API + media serving
│  ├─ config.py         # API key + output directory
│  ├─ schemas.py        # Request/response models
│  └─ services/
│     ├─ script_service.py  # Script generation (religious topics only)
│     ├─ tts_service.py     # Text-to-speech (OpenAI or placeholder)
│     ├─ image_service.py   # Image generation (OpenAI or Pillow)
│     └─ video_service.py   # Video stitching with MoviePy
│
├─ frontend/            # Vite + React + TypeScript UI
│  ├─ src/App.tsx       # Main UI: form + preview
│  ├─ src/style.css     # Simple modern styling
│  └─ ...
│
├─ requirements.txt     # Backend Python deps
└─ README.md
```


## 1. Backend setup (FastAPI)

From the project root:

```bash
cd ai_video_generator_full
python -m venv .venv
# Activate the venv
# Linux / macOS:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\activate

pip install -r requirements.txt
```

### Configure environment variables

In your shell, or in PyCharm Run/Debug configuration:

```bash
export OPENAI_API_KEY="sk-..."        # optional but recommended
export BASE_OUTPUT_DIR="./outputs"    # optional (default: ./outputs)
```

Without `OPENAI_API_KEY`, the app still works, but uses placeholder
text, silent audio, and placeholder images. This is good for debugging.

### Run the backend

```bash
uvicorn app.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- Generated media is served from: http://127.0.0.1:8000/media/...


## 2. Frontend setup (React + Vite)

In another terminal:

```bash
cd ai_video_generator_full/frontend
npm install
npm run dev
```

This starts the Vite dev server (e.g. http://127.0.0.1:5173).

The frontend expects the backend at `http://localhost:8000`.
If you change ports or host, update `API_BASE_URL` in `frontend/src/App.tsx`.


## 3. Using the app

1. Open the frontend in your browser (e.g. http://127.0.0.1:5173).
2. Enter a **religious/spiritual topic** such as:
   - “What is Ramadan?”
   - “Meaning of Diwali in Hinduism”
   - “What is baptism?”
   - “What is the Sabbath?”
3. Adjust style and duration if you like.
4. Click **Generate video**.

The backend will:

1. Generate a neutral, respectful script and scenes (optionally using OpenAI).
2. Generate TTS audio from the script (optionally using OpenAI TTS).
3. Generate one image per scene (OpenAI images or placeholder).
4. Stitch them into a vertical MP4 using MoviePy and serve it via `/media/...`.

The frontend then shows:

- The full script text.
- A scene-by-scene breakdown.
- A video player preview (you can download the video from the player).


## 4. Where to customize

- **Script behaviour**: `app/services/script_service.py`
  - Prompts are explicitly limited to religious/spiritual topics.
  - You can tune tone, scene count, and structure.
- **Text-to-speech**: `app/services/tts_service.py`
  - Swap to another provider or model.
- **Images**: `app/services/image_service.py`
  - Change prompts, style, or replace with stock footage lookup.
- **Video assembly**: `app/services/video_service.py`
  - Add transitions, subtitles, overlays, etc.
- **Frontend UX**: `frontend/src/App.tsx`
  - Change copy, layout, extra fields, or add login later.


## 5. Safety notes

- The backend prompts are designed to:
  - Stay neutral and descriptive.
  - Avoid telling viewers what they should believe.
  - Avoid political topics entirely.
- You should still **review each video manually** before posting to social media,
  especially for sensitive or controversial topics.

---

That’s your starter full‑stack app. You can now focus on debugging,
styling, and expanding features (e.g. saving projects, multiple voices,
and future topic types if you decide to go beyond religious ones).
