# SacredClips – AI Religious Video Generator

**SacredClips** is a full-stack AI application that turns a **religious or spiritual topic**
into a short vertical explainer video ready for **TikTok, Instagram Reels, or YouTube Shorts**.

The system automatically generates:

- a neutral educational **script**
- **scene breakdown**
- **voice narration**
- **AI-generated images**
- a fully rendered **vertical video**

The goal is to create **respectful, educational religious content** using modern AI tools.

SacredClips focuses **only on religious and spiritual topics** and aims to remain **neutral, respectful, and educational**, avoiding persuasion or political messaging.

---

# Features

- AI-generated educational scripts
- Scene-based video structure
- AI-generated images for each scene
- AI text-to-speech narration
- Automatic video assembly using MoviePy
- Adjustable video duration
- In-app **script editing & regeneration**
- Video **preview and download**
- Clean React UI with FastAPI backend

---

# Project structure

```text
SacredClips/
│
├─ app/                 # FastAPI backend
│  ├─ main.py           # API + media serving
│  ├─ config.py         # API key + output directory
│  ├─ schemas.py        # Request/response models
│  │
│  └─ services/
│     ├─ script_service.py  # Script generation (religious topics only)
│     ├─ tts_service.py     # Text-to-speech (OpenAI or placeholder)
│     ├─ image_service.py   # Image generation (OpenAI or Pillow fallback)
│     └─ video_service.py   # Video rendering with MoviePy
│
├─ frontend/            # Vite + React + TypeScript UI
│  ├─ src/App.tsx       # Main UI: form + preview
│  ├─ src/style.css     # Styling
│  └─ ...
│
├─ outputs/             # Generated media files
│  ├─ images
│  ├─ audio
│  └─ videos
│
├─ requirements.txt     # Backend Python dependencies
└─ README.md
```

---

# 1. Backend setup (FastAPI)

From the project root:

```bash
cd SacredClips
python -m venv .venv
```

Activate the virtual environment:

**macOS / Linux**

```bash
source .venv/bin/activate
```

**Windows (PowerShell)**

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# 2. Configure environment variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key_here
BASE_OUTPUT_DIR=outputs
```

If `OPENAI_API_KEY` is **not set**, the app still works but runs in **demo mode**:

- Placeholder images
- Silent audio
- Basic scripts

This allows you to test the pipeline without consuming API credits.

---

# 3. Run the backend

Start the FastAPI server:

```bash
uvicorn app.main:app --reload
```

Backend will run at:

```
http://127.0.0.1:8000
```

Useful endpoints:

API docs:

```
http://127.0.0.1:8000/docs
```

Generated media:

```
http://127.0.0.1:8000/media/...
```

---

# 4. Frontend setup (React + Vite)

Open a new terminal:

```bash
cd frontend
```

Install dependencies:

```bash
npm install
```

Run the development server:

```bash
npm run dev
```

The frontend will run at:

```
http://127.0.0.1:5173
```

The frontend expects the backend at:

```
http://localhost:8000
```

If you change the backend host or port, update:

```
frontend/src/App.tsx
```

---

# 5. Using the app

1. Open the frontend in your browser.

```
http://127.0.0.1:5173
```

2. Enter a **religious or spiritual topic**, for example:

- "What is the meaning of Easter?"
- "What is Ramadan"
- "Meaning of Diwali in Hinduism"
- "What is baptism?"
- "What is the Sabbath?"

3. Choose a narration style.

4. Select a video duration (60–90 seconds recommended).

5. Click **Generate Video**.

---

# 6. What happens behind the scenes

When a video is generated, the backend performs several steps:

### 1. Script generation

`script_service.py`

The system generates a neutral educational script and divides it into scenes.

### 2. Voice narration

`tts_service.py`

The script is converted into speech using OpenAI Text-to-Speech.

### 3. Scene images

`image_service.py`

Each scene receives an AI-generated image based on keywords from the script.

If AI image generation fails, a fallback placeholder is used.

### 4. Video rendering

`video_service.py`

The system:

- loads scene images
- synchronizes them with the narration
- assembles a vertical video using MoviePy
- exports the final MP4

### 5. Media delivery

The finished video is saved in:

```
outputs/.../videos/final_video.mp4
```

and served through:

```
/media/...
```

---

# 7. Editing and regenerating content

SacredClips allows **manual script editing** before rendering the video.

Workflow:

1. Generate the initial script.
2. Edit the script directly in the UI.
3. Click **Regenerate Video**.

The backend will:

- reuse the edited script
- regenerate images
- regenerate narration
- rebuild the video.

This allows precise control over the final output.

---

# 8. Video preview and download

After generation, the frontend displays:

- the full script
- scene breakdown
- video preview
- **download button**

The video can be downloaded as an MP4 and uploaded to social platforms.

---

# 9. Where to customize

## Script behaviour

```
app/services/script_service.py
```

Adjust:

- tone
- number of scenes
- scene length
- narration style

---

## Text-to-speech

```
app/services/tts_service.py
```

You can:

- change voice models
- switch providers
- add multiple voices

---

## Image generation

```
app/services/image_service.py
```

Modify prompts or integrate:

- stock images
- diffusion models
- custom prompt engineering

---

## Video rendering

```
app/services/video_service.py
```

Possible improvements:

- subtitles
- transitions
- overlays
- animated text
- background music

---

## Frontend UX

```
frontend/src/App.tsx
```

You can add:

- project history
- user accounts
- editing tools
- export presets
- direct social media posting

---

# 10. Safety notes

SacredClips is designed to generate **neutral educational content**.

The prompts aim to:

- remain descriptive rather than persuasive
- avoid political discussion
- respect religious diversity

However, AI-generated content should **always be reviewed before publishing**, especially for sensitive topics.

---

# 11. Example Generated Video

Topic: *The Meaning of Advent*

SacredClips automatically generated the following educational short video.

[Watch the generated video here](https://ghana-catholic-community-stuttgart.org/uploads/uploads/b987820034bcc212.mp4)

Generated automatically using:

- OpenAI GPT (script generation)
- OpenAI Images API (scene visuals)
- OpenAI TTS (voice narration)
- MoviePy + FFmpeg (video rendering)

---

# Future Improvements

Possible next steps for the project:

- automatic subtitles
- social media posting integrations
- video templates
- multiple narrator voices
- improved scene transitions
- project saving
- queue-based video rendering
- cloud deployment

---

# License

This project is intended for educational and experimental purposes.
Review generated content before publishing publicly.