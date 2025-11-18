import os
from dotenv import load_dotenv

# Load variables from .env into environment
load_dotenv()

# Read your OpenAI API key from environment variable.
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

# Base directory where generated assets (audio, images, videos) will be stored
BASE_OUTPUT_DIR = os.getenv("BASE_OUTPUT_DIR", "outputs")

os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)