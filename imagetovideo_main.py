from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import os
import tempfile
import requests
import time
from runwayml import RunwayML
import boto3

app = FastAPI()

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RunwayML API key
RUNWAY_API_KEY = os.getenv("RUNWAYML_API_SECRET")
if not RUNWAY_API_KEY:
    raise RuntimeError("RUNWAYML_API_SECRET environment variable is missing")

# AWS Rekognition & S3 setup
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
rekognition = boto3.client(
    "rekognition",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=AWS_REGION
)

# RunwayML client
client = RunwayML(api_key=RUNWAY_API_KEY)

class ImageToVideoRequest(BaseModel):
    prompt_image: HttpUrl
    prompt_text: str = ""
    model: str = "gen4_turbo"
    ratio: str = "1280:720"

def is_image_safe(image_url: str) -> bool:
    """Check image safety using Amazon Rekognition Moderation."""
    try:
        # Download the image bytes
        img_data = requests.get(image_url).content
        
        response = rekognition.detect_moderation_labels(
            Image={"Bytes": img_data},
            MinConfidence=80
        )

        if response.get("ModerationLabels"):
            print("Image flagged:", response["ModerationLabels"])
            return False  # Image contains restricted content
        return True

    except Exception as e:
        print("Rekognition error:", e)
        raise HTTPException(status_code=500, detail=f"Rekognition check failed: {str(e)}")

@app.post("/generate-image-video")
def generate_image_video(request: ImageToVideoRequest):
    try:
        prompt_image_str = str(request.prompt_image)

        # Step 1: Check image safety with Rekognition
        if not is_image_safe(prompt_image_str):
            return {"status": "REJECTED", "reason": "Image failed moderation check"}

        # Step 2: Create the RunwayML task
        task = client.image_to_video.create(
            model=request.model,
            prompt_image=prompt_image_str,
            prompt_text=request.prompt_text,
            ratio=request.ratio
        )

        task_id = task.id

        # Step 3: Poll for completion
        while True:
            task_status = client.tasks.retrieve(task_id)
            if task_status.status in ["SUCCEEDED", "FAILED"]:
                break
            time.sleep(5)

        if task_status.status == "FAILED":
            raise HTTPException(status_code=500, detail="RunwayML task failed.")

        if not task_status.output:
            raise HTTPException(status_code=500, detail="RunwayML task returned no output.")

        video_url = task_status.output[0]
        if not video_url:
            raise HTTPException(status_code=500, detail="RunwayML output missing video URL.")

        # Step 4: Download video
        video_response = requests.get(video_url, stream=True)
        video_response.raise_for_status()

        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        with open(tmp_file.name, "wb") as f:
            for chunk in video_response.iter_content(chunk_size=8192):
                f.write(chunk)

        return FileResponse(tmp_file.name, media_type="video/mp4", filename="generated_video.mp4")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"API error: {str(e)}")

@app.get("/")
def home():
    return {"message": "RunwayML Image-to-Video API with Rekognition moderation is running"}
