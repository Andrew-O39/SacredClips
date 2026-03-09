# SacredClips – AI Religious Video Generator

**SacredClips** is a full-stack AI application that turns a **religious or spiritual topic**
into a short vertical explainer video ready for **TikTok, Instagram Reels, or YouTube Shorts**.

The system automatically generates:

- a neutral educational **script**
- a **scene breakdown**
- **voice narration**
- **AI-generated images**
- a fully rendered **vertical video**

It also supports **direct YouTube publishing** through OAuth 2.0 integration.

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
- Direct **YouTube upload**
- Clean React UI with FastAPI backend

---

# Project structure

```text
SacredClips/
│
├─ app/                 # FastAPI backend
│  ├─ main.py           # API + media serving + YouTube routes
│  ├─ config.py         # API keys + output directory + YouTube config
│  ├─ schemas.py        # Request/response models
│  │
│  └─ services/
│     ├─ script_service.py   # Script generation (religious topics only)
│     ├─ tts_service.py      # Text-to-speech (OpenAI or placeholder)
│     ├─ image_service.py    # Image generation (OpenAI or Pillow fallback)
│     ├─ video_service.py    # Video rendering with MoviePy
│     └─ youtube_service.py  # YouTube OAuth + upload logic
│
├─ frontend/            # Vite + React + TypeScript UI
│  ├─ src/App.tsx       # Main UI: form + preview + YouTube publishing
│  ├─ src/style.css     # Styling
│  └─ ...
│
├─ outputs/             # Generated media files
│  ├─ images
│  ├─ audio
│  ├─ videos
│  └─ youtube_tokens.json
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

# 2. System requirement

SacredClips uses MoviePy for video rendering.  
MoviePy requires **FFmpeg** to be installed on your system.

**macOS**

```bash
brew install ffmpeg
```

**Ubuntu / Debian**

```bash
sudo apt install ffmpeg
```

**Windows**

Download FFmpeg from:

```text
https://ffmpeg.org/download.html
```

Verify installation:

```bash
ffmpeg -version
```

---

# 3. Configure environment variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key_here
BASE_OUTPUT_DIR=outputs

# YouTube integration
GOOGLE_CLIENT_ID=your_google_oauth_client_id
GOOGLE_CLIENT_SECRET=your_google_oauth_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/youtube/callback

# Optional YouTube settings
YOUTUBE_TOKEN_PATH=outputs/youtube_tokens.json
YOUTUBE_UPLOAD_DEFAULT_PRIVACY=unlisted
```

If `OPENAI_API_KEY` is **not set**, the app still works but runs in **demo mode**:

- placeholder images
- silent audio
- simplified script generation

This is useful for development and pipeline testing.

---

# 4. Run the backend

Start the FastAPI server:

```bash
uvicorn app.main:app --reload
```

Backend runs at:

```text
http://127.0.0.1:8000
```

Useful endpoints:

API docs:

```text
http://127.0.0.1:8000/docs
```

Generated media:

```text
http://127.0.0.1:8000/media/...
```

---

# 5. Frontend setup (React + Vite)

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

Frontend runs at:

```text
http://127.0.0.1:5173
```

The frontend expects the backend at:

```text
http://localhost:8000
```

If you change the backend host or port, update `API_BASE_URL` in:

```text
frontend/src/App.tsx
```

---

# 6. Using the app

1. Open the frontend in your browser:

```text
http://127.0.0.1:5173
```

2. Enter a **religious or spiritual topic**, for example:

- "What is baptism in Christianity?"
- "What is the Eucharist?"
- "What is Ramadan?"
- "What is Diwali?"

3. Choose a narration style.

4. Select a video duration (60–90 seconds recommended).

5. Click **Generate Video**.

---

# 7. What happens behind the scenes

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
If image generation fails, a fallback placeholder is used.

### 4. Video rendering

`video_service.py`

The system:

- loads scene images
- synchronizes them with narration
- assembles a vertical video using MoviePy
- exports the final MP4

### 5. Media delivery

The finished video is saved in:

```text
outputs/.../videos/final_video.mp4
```

and served through:

```text
/media/...
```

---

# 8. Editing and regenerating content

SacredClips allows **manual script editing** before rendering the video.

Workflow:

1. Generate the initial script.
2. Edit the script directly in the UI.
3. Click **Regenerate Video**.

The backend will regenerate:

- narration
- scene images
- the final video

using your edited script.

---

# 9. Video preview and download

After generation, the frontend displays:

- the full script
- scene breakdown
- video preview
- **Download MP4** button

The video can be downloaded as an MP4 and uploaded manually to social platforms.

---

# 10. YouTube publishing

SacredClips supports direct upload of generated videos to **YouTube Shorts / YouTube**.

## What is required

You must configure Google OAuth credentials in `.env`:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/youtube/callback
```

## YouTube setup steps

### 1. Create a Google Cloud project
Go to:

```text
https://console.cloud.google.com/
```

Create a project for SacredClips.

### 2. Enable the YouTube Data API v3
In Google Cloud Console:

```text
APIs & Services → Library → YouTube Data API v3 → Enable
```

### 3. Configure OAuth consent screen
In Google Cloud Console:

```text
APIs & Services → OAuth consent screen
```

- Choose **External**
- Add app name (e.g. `SacredClips`)
- Add your email
- Add the scope:

```text
https://www.googleapis.com/auth/youtube.upload
```

- Add your Google account under **Test users**

### 4. Create OAuth client credentials
In Google Cloud Console:

```text
APIs & Services → Credentials → Create Credentials → OAuth Client ID
```

Choose:

```text
Application type: Web application
```

Add this redirect URI exactly:

```text
http://localhost:8000/auth/youtube/callback
```

Download the OAuth JSON or copy the full **Client ID** and **Client Secret**.

### 5. Update `.env`
Copy the values into your `.env` file and restart the backend.

---

## How to connect YouTube

1. Generate a video in SacredClips.
2. In the YouTube Shorts panel, click **Connect YouTube**.
3. Sign in with the Google account that owns the YouTube channel.
4. Approve access.
5. Return to the app and click **Refresh status** if needed.

If successful, the app should show:

```text
Connected to YouTube
```

OAuth tokens are stored locally at:

```text
outputs/youtube_tokens.json
```

for development use.

---

## How to upload to YouTube

After a video has been generated:

1. Enter or edit:
   - YouTube title
   - YouTube description
   - privacy status (`private`, `unlisted`, or `public`)
2. Click **Upload to YouTube**
3. Wait for the upload to complete

The app will return a YouTube link such as:

```text
https://www.youtube.com/watch?v=VIDEO_ID
```

---

# 11. Where to customize

## Script behaviour

```text
app/services/script_service.py
```

Adjust:

- tone
- number of scenes
- scene length
- narration style

## Text-to-speech

```text
app/services/tts_service.py
```

You can:

- change voice models
- switch providers
- add multiple voices

## Image generation

```text
app/services/image_service.py
```

Modify prompts or integrate:

- stock images
- diffusion models
- custom prompt engineering

## Video rendering

```text
app/services/video_service.py
```

Possible improvements:

- subtitles
- transitions
- overlays
- animated text
- background music

## YouTube integration

```text
app/services/youtube_service.py
```

Possible improvements:

- per-user token storage
- multi-user OAuth connections
- better metadata presets
- platform-specific upload workflows

## Frontend UX

```text
frontend/src/App.tsx
```

You can add:

- project history
- user accounts
- editing tools
- export presets
- TikTok integration
- multi-user dashboards

---

# 12. Safety notes

SacredClips is designed to generate **neutral educational content**.

The prompts aim to:

- remain descriptive rather than persuasive
- avoid political discussion
- respect religious diversity

However, AI-generated content should **always be reviewed before publishing**, especially for sensitive topics.

---

# Future Improvements

Possible next steps for the project:

- automatic subtitles
- TikTok integration
- multi-user authentication
- cloud storage for generated assets
- queue-based rendering
- project saving
- multiple narrator voices
- improved scene transitions

---

# License

This project is intended for educational and experimental purposes.  
Review generated content before publishing publicly.