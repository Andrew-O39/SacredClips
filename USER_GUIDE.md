# SacredClips User Guide

This guide describes how to run SacredClips and use **AI mode**, **manual mode**, editing, and **YouTube upload**. For installation and environment variables, see **`README.md`**.

---

## 1. Starting the app

1. **Backend** (project root, virtualenv activated):

   ```bash
   uvicorn app.main:app --reload
   ```

   Default: `http://localhost:8000`

2. **Frontend**:

   ```bash
   cd frontend
   npm run dev
   ```

   Default: `http://localhost:5173`

3. Open the frontend URL in your browser.

---

## 2. Video type and format

- **Normal** vs **Shorts** toggles typical **duration ranges** and defaults **aspect ratio** and **image fit** (e.g. Shorts defaults to **9:16** and **fill**).
- You can set **aspect ratio** explicitly: **16:9** (horizontal), **9:16** (vertical), **1:1** (square).
- **Fit** shows the whole image with padding; **fill** crops to cover the frame (common for vertical video).

---

## 3. Creating AI videos

1. Select **AI** creation mode.
2. Enter a **topic** (religious or spiritual, educational).
3. Set **style** (tone / narrator direction).
4. Set **duration** within the allowed range for the selected aspect ratio.
5. Choose **visual style**, **image fit**, optional **background music** and **volume**, **motion effect** and **intensity**, and **subtitle style**.
6. Click **Generate Video**.

The app requests a **script**, splits it into **scenes**, generates **narration** (OpenAI TTS when configured), **images** per scene, then renders an MP4.

### After generation

- **Script:** View or open **Edit script** to change full narration text, then regenerate from the script panel.
- **Scene editor:** Horizontal **scene cards** show image preview, scene text, keywords, duration. Use **Move Left** / **Move Right** to reorder.
- **Regenerate video from scene edits** (or regenerate from edited script): Rebuilds the video from your current scene cards and script text. Scene images and narration are produced according to each scene’s settings (AI regen for **generate** scenes, reuse for persisted uploads, placeholders where applicable).

---

## 4. Creating manual videos

1. Select **Manual** creation mode.
2. Paste a **script** (required if narration is **TTS**).
3. Use **Split script into scenes** (and **Add scene** as needed) so each card has text, keywords, and duration.
4. For each scene, set **Image source**:
   - **Upload** — choose an image file.
   - **Generate AI image** — keywords + scene text guide generation.
   - **Placeholder** — simple generated placeholder.
5. Choose **narration source**:
   - **Generate AI voice from script** — TTS from your script text.
   - **Upload narration audio** — provide an audio file (supported formats as enforced by the UI/backend).
6. Set the same global options as AI mode (aspect ratio, music, motion, subtitles, etc.) as needed.
7. Submit **Generate** (multipart upload to the backend).

### Scene timing assistant (uploaded narration)

When using **uploaded narration**, you can:

- Preview the audio and optionally place **cuts** on the timeline.
- **Apply cuts to scenes** to align segment lengths with your scene list (see in-app hints for constraints).

This helps match **scene durations** to your audio without manual typing of every length.

---

## 5. Uploaded narration: subtitles and timing

- **Subtitles** use each scene’s **text** field and appear for that scene’s **duration** in the final render.
- The app does **not** perform speech-to-text alignment; subtitle timing follows **scene boundaries**, not detected words in the uploaded file.
- **Recommendation:** Keep **scene text** short enough to read in the time allotted, and use **more scenes** (or **Add scene after** / **Split script**) where the spoken content shifts, so on-screen text stays readable. The UI notes that **Shorts / 9:16** subtitle modes use shorter lines and may use up to **three lines** for the Shorts style.

---

## 6. Uploaded images and persistence

- Initial manual creation sends images via **multipart** form fields per scene.
- After a successful render, the app returns **scene metadata** including `image_mode` and `image_path` where applicable so **regeneration** (JSON) can **reuse** files on disk without re-uploading.
- If you use **Replace scene image** after generation and pick new files, the next regenerate may use **multipart** again for those replacements (see technical guide).

---

## 7. Post-generation scene management

After any video is shown, the **scene editor** includes:

| Control | Purpose |
|---------|---------|
| **Move Left** / **Move Right** | Reorder scenes on the horizontal timeline. |
| **Add scene after** | Inserts a new scene. If the current scene is longer than **2 seconds**, its duration is **split in half** and the new scene receives the other half; otherwise the new scene defaults to **3 seconds** with placeholder image settings. |
| **Duplicate** | Copies text, keywords, duration, and image fields. Two scenes can share the same **`image_path`** (e.g. same uploaded asset) until you change or regenerate them. |
| **Remove** | Deletes a scene (disabled if only one scene remains). |

**Reindexing:** Scene indices are always **1…n** after these operations. Pending **replacement image** file picks are cleared when the structure changes, to avoid wrong file-to-scene mapping—re-select replacements if needed.

---

## 8. Replacing scene images (manual results)

For **manual** (non-AI) rendered videos, each scene card can show **Replace scene image** (file input). Select a new image, then **Regenerate**. Other scenes keep their prior behavior (reuse paths, regenerate AI, or placeholders) according to their `image_mode` / uploads.

---

## 9. Regeneration workflows

| Situation | What the app does |
|-----------|-------------------|
| **AI video**, no replacement files | **JSON** `POST /generate-video-from-scenes` with edited scenes and script text. |
| **Manual video**, no pending replacement image files | Same **JSON** path; optional **uploaded narration** path is sent so narration can be reused. |
| **Manual video**, at least one **replacement** image selected | **Multipart** `POST /manual-video` so new files are sent; narration can be reused via form fields when applicable. |

Always keep **at least one scene** with non-empty text before regenerating, as required by the UI.

---

## 10. Background music

- Choose a **track** or **none**.
- Adjust **volume** (low values are typical so narration stays clear).
- Preview uses the backend **assets** route when available.

---

## 11. Motion effects (recommendations)

| Effect | Typical use |
|--------|----------------|
| **none** | Static slides; maximum readability. |
| **gentle_zoom** | Default-style subtle movement. |
| **slow_pan** | Horizontal drift; stronger at higher intensity. |
| **ken_burns** | Combined zoom + pan; most noticeable at **medium** or **strong** intensity. |

**Intensity** (subtle / medium / strong) scales how far the motion goes. Very short scenes still get motion, but the renderer adapts pacing for short clips.

---

## 12. Subtitles (recommendations)

| Style | Notes |
|-------|--------|
| **off** | No burned-in subtitles. |
| **minimal** | Discreet, up to two lines; font may shrink to fit. |
| **cinematic** | Slightly larger, with stroke for contrast. |
| **shorts** | Short lines, up to **three** lines when needed; tuned for **9:16** / Shorts reading. |

If text is **cut off** or hard to read, shorten the **scene text**, split into **more scenes**, or pick a style suited to vertical layout. This is layout and chunking behavior—not word-level caption timing.

---

## 13. YouTube upload

1. Configure Google OAuth in `.env` (see `README.md`).
2. Generate a video.
3. **Connect YouTube**, complete the browser flow, **Refresh status** if needed.
4. Set title, description, privacy, then **Upload to YouTube**.

Tokens are stored locally (default under your output directory). Use **Unlisted** for first tests.

---

## 14. Where files are saved

Under **`BASE_OUTPUT_DIR`** (default `outputs/`):

```text
outputs/<topic_slug>/audio/
outputs/<topic_slug>/images/
outputs/<topic_slug>/videos/final_video.mp4
```

YouTube OAuth token file path defaults under the same base directory unless overridden.

---

## 15. Troubleshooting

### Placeholder images

- OpenAI image generation failed, API key missing, or network/quota errors.
- Check backend logs. Fix the key or retry.

### OpenAI quota / billing errors

- Symptoms: failed script, TTS, or image steps; logs show API errors.
- Verify billing and model access on your OpenAI account; reduce usage or upgrade limits.

### Narration missing or silent

- Missing key → placeholder **empty** audio file may be created; video may have **no usable narration** if nothing valid is on disk.
- Confirm `OPENAI_API_KEY` and successful TTS logs for AI paths.

### Subtitle timing feels wrong (uploaded narration)

- Subtitles follow **scene timing**, not detected speech.
- **Fix:** Shorter per-scene text, more scenes, timing assistant cuts, or **Add scene after** to split content.

### Subtitle text missing or cut off

- Usually too much text for the width or line budget.
- Use **shorter lines**, **Shorts** style on vertical video, or split scenes. See on-app subtitle hints.

### YouTube “Not connected” or upload failures

- Confirm OAuth env vars, redirect URI, test users, and API enablement in Google Cloud.
- Use **Refresh status**; restart backend after `.env` changes.

### Video preview does not play

- Ensure backend is running and the browser can reach `localhost:8000` (CORS is configured for the Vite dev origin).

---

## 16. Responsible use

Treat SacredClips as a **drafting tool**. Verify accuracy and respectful representation before publishing.
