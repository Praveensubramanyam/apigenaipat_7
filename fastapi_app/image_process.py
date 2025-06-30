from azure.ai.vision.imageanalysis.models import VisualFeatures
from io import BytesIO
from fastapi import HTTPException

app = None
search_index = None

def set_search_index(func):
    global search_index
    search_index = func

def set_app(application):
    global app
    app = application

async def analyze_image_with_vision(image_data: bytes):
    try:
        vision_client = app.state.vision_client
        image_str = BytesIO(image_data)

        result = vision_client.analyze(
            image_data=image_str,
            visual_features=[
                VisualFeatures.READ,
                VisualFeatures.CAPTION
            ]
        )

        analysis_result = {
            "caption": '',
            "tags": [],
            "objects": [],
            "text": [],
        }

        if hasattr(result, 'caption'):
            c = getattr(result, 'caption')
            if callable(c):
                c = c()
            if hasattr(c, 'text'):
                analysis_result["caption"] = c.text
            elif isinstance(c, dict):
                analysis_result["caption"] = c.get('text', '')

        tags = getattr(result, 'tags', []) or []
        analysis_result["tags"] = [tag.name for tag in tags]

        objects = getattr(result, 'objects', []) or []
        analysis_result["objects"] = [{"name": obj.name, "confidence": obj.confidence} for obj in objects]

        if hasattr(result, 'read') and getattr(result.read, 'blocks', None):
            blocks = result.read.blocks or []
            for text_result in blocks:
                for line in text_result.lines:
                    analysis_result["text"].append(line.text)

        return analysis_result

    except Exception as e:
        raise Exception(f"Computer Vision analysis failed: {str(e)}")

async def process_image_for_vision(image_content: bytes, blob_name: str):
    try:
        vision_re = await analyze_image_with_vision(image_content)
        return {
            "blob_name": blob_name,
            "file_type": "image",
            "results": {
                "image": [{
                    "image_index": 0,
                    "blob_name": blob_name,
                    "vision_analyzed": vision_re
                }]
            }
        }
    except Exception as e:
        raise Exception(f"Error processing image: {str(e)}")

async def image_process(blob_name: str):
    try:
        blob_client = app.state.container_client.get_blob_client(blob_name)
        blob_data = blob_client.download_blob()
        file_content = blob_data.readall()

        file_extension = blob_name.split('.')[-1].lower() if '.' in blob_name else ''

        if file_extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff']:
            AI_search_content = await process_image_for_vision(file_content, blob_name)
        else:
            raise HTTPException(
                status_code=400,
                detail="Kindly upload files in image format (e.g., jpg, png, bmp, gif, tiff)."
            )

        pt = await search_index(blob_name, AI_search_content)

        return {
            "search_result": pt,
            "vision_content": AI_search_content,
            "processed": True,
        }

    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Computer Vision processing failed: {str(e)}"
        )
