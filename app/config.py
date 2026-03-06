import os
from dotenv import load_dotenv

# Load variables from .env into environment
load_dotenv()

# Read your OpenAI API key from environment variable.
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

# Base directory where generated assets (audio, images, videos) will be stored
BASE_OUTPUT_DIR = os.getenv("BASE_OUTPUT_DIR", "outputs")

os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)

# YouTube / Google OAuth configuration
GOOGLE_CLIENT_ID: str | None = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET: str | None = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI: str | None = os.getenv("GOOGLE_REDIRECT_URI")

# Where to store OAuth tokens locally for development
YOUTUBE_TOKEN_PATH: str = os.getenv(
    "YOUTUBE_TOKEN_PATH",
    os.path.join(BASE_OUTPUT_DIR, "youtube_tokens.json"),
)

# Default privacy for uploaded videos (private / unlisted / public)
YOUTUBE_UPLOAD_DEFAULT_PRIVACY: str = os.getenv(
    "YOUTUBE_UPLOAD_DEFAULT_PRIVACY",
    "unlisted",
)