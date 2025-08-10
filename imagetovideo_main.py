from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import os
import tempfile
import requests
import time
from runwayml import RunwayML

app = FastAPI()

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure API key is set
RUNWAY_API_KEY = os.getenv("RUNWAYML_API_SECRET")
if not RUNWAY_API_KEY:
    raise RuntimeError("RUNWAYML_API_SECRET environment variable is missing")

# Initialize RunwayML client
client = RunwayML(api_key=RUNWAY_API_KEY)

# Request schema
class ImageToVideoRequest(BaseModel):
    prompt_image: HttpUrl
    prompt_text: str = ""
    model: str = "gen4_turbo"
    ratio: str = "1280:720"

@app.post("/generate-image-video")
def generate_image_video(request: ImageToVideoRequest):
    try:
        # Convert HttpUrl to string explicitly
        prompt_image_str = str(request.prompt_image)

        # Create the generation task
        task = client.image_to_video.create(
            model=request.model,
            prompt_image=prompt_image_str,
            prompt_text=request.prompt_text,
            ratio=request.ratio
        )

        task_id = task.id  # Store task ID for polling

        # Poll until task finishes
        while True:
            task_status = client.tasks.retrieve(task_id)
            if task_status.status in ["SUCCEEDED", "FAILED"]:
                break
            time.sleep(5)  # Wait before checking again

        if task_status.status == "FAILED":
            raise HTTPException(status_code=500, detail="RunwayML task failed.")

        if not task_status.output:
            raise HTTPException(status_code=500, detail="RunwayML task returned no output.")

        # Extract video URL
        video_url = task_status.output[0].get("video")
        if not video_url:
            raise HTTPException(status_code=500, detail="RunwayML output missing 'video' key.")

        # Download video
        video_response = requests.get(video_url, stream=True)
        video_response.raise_for_status()

        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        with open(tmp_file.name, "wb") as f:
            for chunk in video_response.iter_content(chunk_size=8192):
                f.write(chunk)

        return FileResponse(tmp_file.name, media_type="video/mp4", filename="generated_video.mp4")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RunwayML API error: {str(e)}")

@app.get("/")
def home():
    return {"message": "RunwayML Image-to-Video API is running"}
