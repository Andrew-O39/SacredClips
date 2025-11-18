import os
from pathlib import Path
from typing import List

from moviepy import ImageClip, AudioFileClip, concatenate_videoclips

MIN_DURATION = 60.0  # seconds
MAX_DURATION = 90.0  # seconds


def render_video(
    image_paths: List[str],
    audio_path: str,
    scene_durations: List[float],
    output_dir: str,
    filename: str = "final_video.mp4",
) -> str:
    """
    Combine images + audio into a vertical MP4.

    Rules:
    - Use given scene_durations for initial layout.
    - If audio is present, sync video length to audio where reasonable.
    - Clamp overall length to [MIN_DURATION, MAX_DURATION]:
        * If content would exceed MAX_DURATION, trim.
        * If content shorter than MIN_DURATION, pad with last image (silent).
    """
    os.makedirs(output_dir, exist_ok=True)
    output_path = str(Path(output_dir) / filename)

    clips: List[ImageClip] = []

    for img_path, duration in zip(image_paths, scene_durations):
        safe_duration = max(float(duration), 0.2)
        clip = ImageClip(img_path, duration=safe_duration)

        try:
            clip = clip.resized(height=1080)  # MoviePy 2.x
        except AttributeError:
            clip = clip.resize(height=1080)   # MoviePy 1.x

        clips.append(clip)

    if not clips:
        raise RuntimeError("render_video: no image clips were created")

    video = concatenate_videoclips(clips, method="compose")

    use_audio = (
        audio_path
        and os.path.exists(audio_path)
        and os.path.getsize(audio_path) > 0
    )

    if use_audio:
        try:
            audio = AudioFileClip(audio_path)

            # First clamp both to MAX_DURATION if needed
            if video.duration > MAX_DURATION:
                try:
                    video = video.subclipped(0, MAX_DURATION)  # MoviePy 2.x
                except AttributeError:
                    video = video.subclip(0, MAX_DURATION)     # MoviePy 1.x

            if audio.duration > MAX_DURATION:
                try:
                    audio = audio.subclipped(0, MAX_DURATION)  # MoviePy 2.x
                except AttributeError:
                    audio = audio.subclip(0, MAX_DURATION)     # MoviePy 1.x

            # Now sync video to audio as before
            if audio.duration > video.duration:
                # Trim audio down to video
                try:
                    audio = audio.subclipped(0, video.duration)
                except AttributeError:
                    audio = audio.subclip(0, video.duration)
            elif audio.duration + 0.1 < video.duration:
                # Trim video down to audio
                try:
                    video = video.subclipped(0, audio.duration)
                except AttributeError:
                    video = video.subclip(0, audio.duration)

            # Attach audio
            try:
                video = video.with_audio(audio)  # 2.x
            except AttributeError:
                video = video.set_audio(audio)   # 1.x

        except Exception as e:
            print(f"[render_video] Could not load audio '{audio_path}': {e}")

    else:
        # No audio: still enforce max length
        if video.duration > MAX_DURATION:
            try:
                video = video.subclipped(0, MAX_DURATION)
            except AttributeError:
                video = video.subclip(0, MAX_DURATION)

    # At this point, video.duration <= MAX_DURATION.
    final = video

    # Ensure final duration is at least MIN_DURATION by padding the last frame (silent)
    if final.duration < MIN_DURATION:
        pad = MIN_DURATION - final.duration
        last_img_path = image_paths[-1]
        pad_clip = ImageClip(last_img_path, duration=pad)
        try:
            pad_clip = pad_clip.resized(height=1080)
        except AttributeError:
            pad_clip = pad_clip.resize(height=1080)

        final = concatenate_videoclips([final, pad_clip], method="compose")
        pad_clip.close()

    final.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
    )

    # Cleanup
    for c in clips:
        c.close()
    final.close()

    return output_path