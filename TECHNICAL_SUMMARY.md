# SacredClips – Technical Implementation Summary

SacredClips is an AI-powered full-stack application that generates short educational videos about religious or spiritual topics. The system automatically produces a structured script, generates scene images, synthesizes voice narration, renders a vertical video optimized for short-form platforms, and supports direct publishing to YouTube.

The application demonstrates how modern AI APIs, media-processing tools, and web technologies can be combined into an automated multimedia content creation pipeline.

---

# System Architecture

The application follows a client-server architecture.

The frontend collects user input and interacts with a FastAPI backend through HTTP APIs.  
The backend orchestrates AI content generation, media rendering, and publishing.

```text
React Frontend (Vite + TypeScript)
        |
        | HTTP API
        v
FastAPI Backend (Python)
        |
        | AI Services + Publishing Services
        v
OpenAI APIs (script, images, TTS) + YouTube Data API
        |
        v
Video Rendering (MoviePy + FFmpeg)
        |
        v
Generated Media Files (outputs/)
```

---

# Core Technology Stack

## Backend

Language:
- Python 3.12

Framework:
- FastAPI

Server:
- Uvicorn

Configuration:
- python-dotenv
- environment variables (`.env`)

Validation and schemas:
- Pydantic

Backend responsibilities:

- request handling
- script generation orchestration
- image generation
- text-to-speech generation
- video rendering pipeline
- local media serving
- YouTube OAuth handling
- YouTube upload orchestration
- error handling and fallback mechanisms

---

## Frontend

Framework:
- React

Language:
- TypeScript

Build tool:
- Vite

Frontend responsibilities:

- user input forms
- video topic collection
- narration style selection
- duration selection
- generated script display
- script editing and regeneration
- scene breakdown display
- video preview and download
- YouTube connection and upload UI

Communication:
- Fetch API to interact with FastAPI endpoints

---

# AI Integration

SacredClips integrates multiple OpenAI capabilities.

## Script Generation

Used to generate structured educational scripts from a user-provided topic.

Technologies:
- OpenAI API
- GPT-based language models

Responsibilities:
- generate neutral educational scripts
- structure script into scenes
- provide scene text
- provide scene keywords for image prompts

---

## Image Generation

Scene visuals are generated using OpenAI image generation.

Technologies:
- OpenAI Images API

Responsibilities:
- generate one image per scene
- align visuals with scene keywords
- fall back to placeholder images if generation fails

---

## Text-to-Speech

Narration is automatically generated from the script.

Technologies:
- OpenAI Text-to-Speech

Responsibilities:
- convert script text to spoken narration
- export narration to MP3
- synchronize narration with the generated video

---

# Video Rendering Pipeline

Video assembly is performed locally on the backend.

Technologies:
- MoviePy
- FFmpeg
- Pillow (for placeholder image generation)

Process:

1. Generate or load scene images
2. Create timed clips for each scene
3. Concatenate scene clips
4. Generate narration audio
5. Attach the narration track to the video
6. Export the final vertical MP4

Output format:

```text
MP4 (H.264 video + AAC audio)
```

Aspect ratio:

```text
9:16 vertical video
```

Intended publishing targets:

- TikTok
- Instagram Reels
- YouTube Shorts

---

# YouTube Publishing Integration

A YouTube publishing workflow was added to the application so that generated videos can be uploaded directly from the frontend.

## Technologies used

- Google OAuth 2.0
- YouTube Data API v3
- google-auth
- google-auth-oauthlib
- google-api-python-client

## Backend implementation

A dedicated backend service was added:

```text
app/services/youtube_service.py
```

Responsibilities:
- initiate OAuth flow
- generate authorization URL
- handle OAuth state verification
- handle PKCE code verifier persistence
- exchange authorization code for tokens
- store OAuth tokens locally for development
- refresh expired tokens
- upload generated MP4 files to YouTube

## OAuth flow

The backend implements:

- `GET /auth/youtube/start`
- `GET /auth/youtube/callback`
- `GET /auth/youtube/status`

The callback flow includes:

- state verification
- PKCE code verifier reuse
- token persistence
- connection status checking

## Upload flow

The backend implements:

- `POST /publish/youtube`

This endpoint uploads the generated MP4 file with user-defined:

- title
- description
- privacy status (`private`, `unlisted`, `public`)

The response returns:

- YouTube video ID
- YouTube URL

## Frontend implementation

The React frontend includes a YouTube publishing section with:

- **Connect YouTube** button
- connection status display
- title input
- description input
- privacy selector
- **Upload to YouTube** button
- success link display

This allows the user to move from:

```text
topic → generation → preview → publish
```

within a single workflow.

---

# Project Structure

```text
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
│       ├── video_service.py
│       └── youtube_service.py
│
├── frontend
│   ├── src
│   │   └── App.tsx
│   └── index.html
│
├── outputs
│   ├── images
│   ├── audio
│   ├── videos
│   └── youtube_tokens.json
│
├── requirements.txt
├── README.md
├── USER_GUIDE.md
└── TECHNICAL_SUMMARY.md
```

---

# Key Features Implemented

## Automated Script Generation
Generates structured educational scripts from a user-provided topic.

## Scene-Based Video Construction
Scripts are divided into scenes for structured visual storytelling.

## AI Image Generation
Each scene receives a corresponding visual illustration.

## AI Voice Narration
Narration is automatically generated using AI text-to-speech.

## Automated Video Rendering
Scene visuals and narration are synchronized and rendered into a final vertical video.

## In-App Script Editing
Users can edit the generated script and regenerate the video.

## Video Preview and Download
The frontend allows previewing the generated video and downloading it as MP4.

## Direct YouTube Publishing
Users can authenticate with YouTube and upload generated videos directly from the application.

---

# Data and Media Storage

Generated assets are stored locally during development.

Directory structure:

```text
outputs/
   topic_name/
      images/
      audio/
      videos/
```

YouTube OAuth tokens are currently stored locally for development at:

```text
outputs/youtube_tokens.json
```

Generated media is served through the FastAPI static media route:

```text
/media/...
```

---

# Error Handling and Fallbacks

The system includes multiple resilience mechanisms.

## AI service fallback examples

If OpenAI services fail:

- placeholder images are generated
- simplified scripts can be used
- manual script editing is still available

## Publishing safeguards

The YouTube upload service includes:

- OAuth state verification
- PKCE handling
- token refresh logic
- upload path validation to ensure uploaded files originate from the configured output directory
- explicit error handling for unauthorized or invalid publishing states

These mechanisms ensure the application remains usable and safer during development.

---

# Security Practices

Sensitive information is handled using environment variables.

Examples:

```text
OPENAI_API_KEY
BASE_OUTPUT_DIR
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI
YOUTUBE_TOKEN_PATH
YOUTUBE_UPLOAD_DEFAULT_PRIVACY
```

These values are stored in `.env` and excluded from version control using `.gitignore`.

Current security considerations implemented:

- local secret management through `.env`
- exclusion of secrets from Git tracking
- YouTube OAuth state verification
- PKCE code verifier storage and reuse
- output-path validation for YouTube uploads

---

# Development Tooling

Version control:
- Git
- GitHub

Environment setup:
- Python virtual environments
- npm for frontend dependency management

Developer support:
- README.md
- USER_GUIDE.md
- TECHNICAL_SUMMARY.md

---

# Potential Future Improvements

Possible extensions to the system include:

- TikTok integration
- automatic subtitle generation
- multi-language support
- voice selection
- animated captions
- cloud storage for media assets
- background job processing
- multi-user authentication
- saved projects and dashboards
- queue-based video rendering
- production-grade OAuth token storage
- social media publishing history

---

# Summary

SacredClips demonstrates how modern AI APIs can be integrated into a full-stack application to automate the creation of short-form educational videos.

The project combines:

- natural language generation
- image synthesis
- speech synthesis
- video rendering
- frontend editing workflows
- OAuth-based social media publishing

into a cohesive, working product.

It is both a practical content-generation system and a strong demonstration of full-stack AI engineering, API integration, media processing, and product-oriented software design.