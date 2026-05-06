from typing import List, Literal, Optional
from pydantic import BaseModel, Field

VisualStyle = Literal[
    "Classical sacred art",
    "Cinematic realism",
    "Historical documentary",
    "Warm candlelit painting",
    "Minimal reverent illustration",
]

AspectRatio = Literal["16:9", "9:16", "1:1"]
ImageFitMode = Literal["fit", "fill"]


class Scene(BaseModel):
    index: int = Field(ge=1)
    text: str = Field(min_length=1)
    keywords: List[str] = Field(default_factory=list, max_length=10)
    duration_seconds: float = Field(gt=0, le=120)
    # Populated server-side after image generation — optional on requests.
    image_url: Optional[str] = None


class VideoRequest(BaseModel):
    topic: str = Field(min_length=1)
    style: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0, le=600)
    visual_style: VisualStyle = "Classical sacred art"
    aspect_ratio: AspectRatio = "16:9"
    image_fit_mode: ImageFitMode = "fit"


class ManualVideoRequest(BaseModel):
    """
    Used when the user edits the script in the UI and wants to regenerate the video.

    We reuse scenes (durations & keywords) from the previous run,
    but TTS + images + video are rebuilt from the edited script_text.
    """
    topic: str = Field(min_length=1)
    style: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0, le=600)
    script_text: str = Field(min_length=1)
    scenes: List[Scene] = Field(min_length=1)
    visual_style: VisualStyle = "Classical sacred art"
    aspect_ratio: AspectRatio = "16:9"
    image_fit_mode: ImageFitMode = "fit"


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
    video_path: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    privacy_status: Literal["private", "unlisted", "public"] = "unlisted"


class YouTubePublishResponse(BaseModel):
    youtube_video_id: str
    youtube_url: str