from image_process import set_search_index

app = None

def set_app_flat(application):
    global app
    app = application

async def flatten_content(blob_name: str, content: dict):
    doc_id = blob_name.replace('/', '_').replace('.', '_')

    flattened_doc = {
        "id": doc_id,
        "blob_name": blob_name,
        "file_type": content.get("file_type", "unknown"),
        "content": "",
        "metadata": {}
    }

    results = content.get("results", {})

    if "image" in results:
        image_data = results["image"]
        all_texts = []
        all_tags = []
        all_objects = []
        captions = []

        for img in image_data:
            vision_data = img.get("vision_analyzed", {})

            if vision_data.get("caption"):
                captions.append(vision_data["caption"])

            if vision_data.get("text"):
                all_texts.extend(vision_data["text"])

            if vision_data.get("tags"):
                all_tags.extend(vision_data["tags"])

            if vision_data.get("objects"):
                all_objects.extend([obj["name"] for obj in vision_data["objects"]])

        combined_content = []

        if captions:
            combined_content.append("Image descriptions: " + " | ".join(captions))

        if all_texts:
            combined_content.append("Extracted text: " + " | ".join(all_texts))

        if all_tags:
            combined_content.append("Tags: " + " | ".join(all_tags))

        if all_objects:
            combined_content.append("Detected objects: " + " | ".join(all_objects))

        flattened_doc["content"] = "\n\n".join(combined_content)

        flattened_doc["metadata"] = {
            "captions": captions,
            "tags": list(set(all_tags)),
            "objects": list(set(all_objects)),
            "ocr_text": all_texts,
        }

    else:
        # Unsupported content type
        flattened_doc["content"] = "Kindly upload files in image format."
        flattened_doc["metadata"] = {
            "error": "Non-image content provided"
        }

    return flattened_doc

async def search_index(blob_name: str, content: dict):
    try:
        search_client = app.state.search_client

        flattened_document = await flatten_content(blob_name, content)

        result = search_client.upload_documents([flattened_document])

        print(result[0])

        return {
            "status": "success",
            "document_id": flattened_document["id"],
            "blob_name": blob_name,
        }

    except Exception as e:
        raise Exception(f"Search indexing failed: {str(e)}")

set_search_index(search_index)
