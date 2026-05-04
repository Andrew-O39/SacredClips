from typing import List, Literal
from pydantic import BaseModel

VisualStyle = Literal[
    "Classical sacred art",
    "Cinematic realism",
    "Historical documentary",
    "Warm candlelit painting",
    "Minimal reverent illustration",
]


class Scene(BaseModel):
    index: int
    text: str
    keywords: List[str]
    duration_seconds: float


class VideoRequest(BaseModel):
    topic: str
    style: str
    platform: str
    duration_seconds: float
    visual_style: VisualStyle = "Classical sacred art"


class ManualVideoRequest(BaseModel):
    """
    Used when the user edits the script in the UI and wants to regenerate the video.

    We reuse scenes (durations & keywords) from the previous run,
    but TTS + images + video are rebuilt from the edited script_text.
    """
    topic: str
    style: str
    platform: str
    duration_seconds: float
    script_text: str
    scenes: List[Scene]
    visual_style: VisualStyle = "Classical sacred art"


class VideoResponse(BaseModel):
    video_path: str
    video_url: str
    script_text: str
    scenes: List[Scene]
    used_ai: bool


class YouTubeAuthStartResponse(BaseModel):
    auth_url: str


class YouTubeAuthStatus(BaseModel):
    connected: bool


class YouTubePublishRequest(BaseModel):
    video_path: str
    title: str
    description: str
    privacy_status: Literal["private", "unlisted", "public"] = "unlisted"


class YouTubePublishResponse(BaseModel):
    youtube_video_id: str
    youtube_url: str