# SacredClips – Technical Implementation Summary

SacredClips is an AI-powered full-stack application that generates short educational videos about religious or spiritual topics. The system automatically produces a structured script, generates scene images, synthesizes voice narration, and renders a vertical video optimized for social media platforms such as TikTok, Instagram Reels, and YouTube Shorts.

The application demonstrates the integration of modern AI APIs with a scalable backend and a responsive frontend to automate multimedia content creation.

---

# System Architecture

The application follows a **client–server architecture**.

Frontend and backend communicate through a REST API.

```
React Frontend (Vite + TypeScript)
        |
        | HTTP API
        v
FastAPI Backend (Python)
        |
        | AI Services
        v
OpenAI APIs (script, images, TTS)
        |
        v
Video Rendering (MoviePy + FFmpeg)
        |
        v
Generated Media Files (outputs/)
```

---

# Technology Stack

## Backend

Language:
- Python 3.12

Framework:
- FastAPI

Server:
- Uvicorn (ASGI server)

Configuration:
- python-dotenv
- environment variables (.env)

Data validation:
- Pydantic models

Backend responsibilities:

- REST API endpoints
- script generation orchestration
- image generation
- text-to-speech generation
- video rendering pipeline
- media serving
- error handling and fallback mechanisms

---

## AI Integration

SacredClips integrates multiple OpenAI capabilities.

### Script Generation

Used to generate structured educational scripts.

Technologies:
- OpenAI API
- GPT language models

Responsibilities:
- generate neutral educational scripts
- structure script into scenes
- produce scene keywords for image prompts

---

### Image Generation

Scene images are generated using OpenAI's image generation API.

Technologies:
- OpenAI Images API

Responsibilities:
- generate scene illustrations
- match visuals to scene keywords
- provide fallback placeholder images if generation fails

---

### Text-to-Speech

Narration is generated automatically from the script.

Technologies:
- OpenAI Text-to-Speech

Responsibilities:
- convert script text to spoken narration
- export audio as MP3
- synchronize audio with scene durations

---

# Video Rendering Pipeline

Video assembly is performed locally on the backend.

Technologies:
- MoviePy
- FFmpeg

Process:

1. Load scene images.
2. Create timed video clips for each scene.
3. Concatenate scene clips.
4. Attach narration audio track.
5. Export final vertical video.

Output format:

```
MP4 (H.264 video + AAC audio)
```

Typical aspect ratio:

```
9:16 (vertical video)
```

---

# Frontend

Framework:
- React

Language:
- TypeScript

Build tool:
- Vite

Frontend responsibilities:

- user input interface
- video topic form
- narration style selection
- duration selection
- API request handling
- script display
- scene breakdown display
- video preview player
- video download button

The frontend communicates with the backend using the Fetch API.

---

# Project Structure

```
SacredClips/
│
├── app
│   ├── main.py
│   ├── config.py
│   ├── schemas.py
│   │
│   └── services
│       ├── script_service.py
│       ├── image_service.py
│       ├── tts_service.py
│       └── video_service.py
│
├── frontend
│   ├── src
│   │   └── App.tsx
│   └── index.html
│
├── outputs
│   ├── images
│   ├── audio
│   └── videos
│
├── requirements.txt
└── README.md
```

---

# Key Features Implemented

### Automated Script Generation
Generates structured educational scripts from a user-provided topic.

### Scene-Based Video Construction
Scripts are divided into scenes for structured video composition.

### AI Image Generation
Each scene receives a corresponding visual illustration.

### AI Voice Narration
Narration is automatically generated using AI text-to-speech.

### Automated Video Rendering
Scene visuals and narration are synchronized and rendered into a final video.

### In-App Script Editing
Users can edit the generated script and regenerate the video.

### Video Preview and Download
The frontend allows previewing the generated video and downloading it.

---

# Media Storage

Generated assets are stored locally.

Directory structure:

```
outputs/
   topic_name/
      images/
      audio/
      videos/
```

The backend serves generated media via:

```
/media/...
```

---

# Error Handling and Fallbacks

The system includes several resilience mechanisms.

Examples:

If OpenAI services fail:

- placeholder images are generated
- silent audio can be used
- manual script editing is supported

This ensures the application remains usable even without AI services.

---

# Security Practices

Sensitive information is handled using environment variables.

Examples:

```
OPENAI_API_KEY
BASE_OUTPUT_DIR
```

These values are stored in `.env` and excluded from version control using `.gitignore`.

---

# Potential Future Improvements

Possible extensions to the system include:

- automatic subtitle generation
- multi-language support
- voice selection
- animated captions
- social media publishing integration
- user accounts and saved projects
- background music integration
- cloud-based rendering pipeline

---

# Summary

SacredClips demonstrates how modern AI APIs can be integrated into a full-stack application to automate the creation of short-form educational videos.

The project combines natural language generation, image synthesis, speech synthesis, and video rendering into a cohesive workflow, delivered through a web-based interface.