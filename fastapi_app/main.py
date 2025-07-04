from azure.search.documents import SearchClient
from azure.keyvault.secrets import SecretClient
from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from azure.identity.aio import DefaultAzureCredential
from openai import AzureOpenAI
import redis.asyncio as redis
import logging
import hashlib
import json
from typing import Optional, Any
from fastapi.middleware.cors import CORSMiddleware

from fastapi import FastAPI, File, UploadFile, HTTPException,Request , Body
from contextlib import asynccontextmanager

from image_process import image_process,set_app
from Flatten_doc import set_app_flat
from key_vault import kv_uri, CONFIG


REDIS_CONFIG = {
    "host" : CONFIG["redis_url"],
    "port" : CONFIG["redis_port"],
    "password" : CONFIG["redis_password"],
    "ssl": True,
    "ssl_cert_reqs": None,
    "decode_responses": True,
    "socket_timeout": 30,
    "socket_connect_timeout": 30,
    "retry_on_timeout": True
}  

CACHE_TTL = {
    "search_results": 3600,      # 1 hour
    "openai_responses": 7200,    # 2 hours
    "upload_metadata": 86400,    # 24 hours
    "vision_analysis": 3600,     # 1 hour
    "blob_info": 1800           # 30 minutes
}

class RedisCache:

    def __init__(self):
        self.redis_client = None
        self.connected    = False

    async def connect(self):
        try:
            self.redis_client = redis.Redis(**REDIS_CONFIG)
            await self.redis_client.ping()
            self.connected = True
            logging.info("Connected to Azure Redis Cache")

        except Exception as e:
            self.connected = False
            logging.error(f"Redis connection failed: {str(e)}")

    async def disconnect(self):
        if self.redis_client:
            await self.redis_client.close()
    
    def _generate_cache_key(self,prefix:str,identifier: str) -> str:
        hash_obj = hashlib.md5(identifier.encode())
        return f"{prefix}:{hash_obj.hexdigest()}"

    async def get(self,key:str) -> Optional[Any]:
        if not self.connected:
            return None
    
        try:
            cached_data = await self.redis_client.get(key)
            if cached_data:
                return json.loads(cached_data)
            return None
        
        except Exception as e:
            logging.error(f"Cache get error: {str(e)}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """Set value in cache with TTL"""
        if not self.connected:
            return False
        
        try:
            serialized_value = json.dumps(value, default=str)
            await self.redis_client.setex(key, ttl, serialized_value)
            return True
        except Exception as e:
            logging.error(f"Cache set error: {str(e)}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self.connected:
            return False
        
        try:
            await self.redis_client.delete(key)
            return True
        except Exception as e:
            logging.error(f"Cache delete error: {str(e)}")
            return False
    
    async def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern"""
        if not self.connected:
            return 0
        
        try:
            keys = await self.redis_client.keys(pattern)
            if keys:
                return await self.redis_client.delete(*keys)
            return 0
        except Exception as e:
            logging.error(f"Cache clear error: {str(e)}")
            return 0

cache = RedisCache()

@asynccontextmanager
async def lifespan(app: FastAPI):

    try:
        app.state.search_client = SearchClient(
            endpoint= CONFIG["search_endpoint"],
            index_name= CONFIG["search_index"],
            credential= AzureKeyCredential(CONFIG["search_key"])
        )

        app.state.secret_client =  SecretClient(
            credential=DefaultAzureCredential(),
            vault_url       = kv_uri
        )
        app.state.vision_client = ImageAnalysisClient(
                endpoint    = "https://eastus.api.cognitive.microsoft.com/",#CONFIG["vision_endpoint"],
                credential=AzureKeyCredential(CONFIG["vision_key"])
        )
        
        app.state.blob_client = BlobServiceClient.from_connection_string(CONFIG["adls_connection_string"])
        app.state.container_client = app.state.blob_client.get_container_client(CONFIG["adls_container"])

        await cache.connect()
        app.state.cache = cache
        yield
    finally: 
        await cache.disconnect()

app = FastAPI(lifespan=lifespan)
set_app(app)
set_app_flat(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or specify your Streamlit app origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    return {"status": "healthy"}


@app.post("/upload_file/")
async def upload_file(file: UploadFile = File(...)):
    try :

        blob_client = app.state.container_client.get_blob_client(file.filename)
        content = await file.read()
        file_hash = hashlib.md5(content).hexdigest()
        cache_key = cache._generate_cache_key("Upload",f"{file.filename}_{file_hash}")
        cached_result = await cache.get(cache_key)
        blob_client.upload_blob(content,overwrite= True)
        pors = str(blob_client.blob_name).replace('.','_') 
        image_process_task = await image_process(blob_client.blob_name)

        result = {"message": f"File '{file.filename}' uploaded successfully!",
                "blob name": pors,
                 "container": blob_client.container_name,
                  "file_hash": file_hash,
                   "cached": False }
    
        await cache.set(cache_key,result,CACHE_TTL["upload_metadata"])

        return result


    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/openai/")
async def generate_response(request: Request , body:dict = Body(...)):
    print(f"openai end point: ")
    print(f"openai key: ")

    try:
        document_id = body.get("doc_id")
        user_query = body.get("query", "")
        search_client = app.state.search_client


        if not document_id:
            raise HTTPException(status_code=400, detail="Document ID is required")
        query_identifier = f"{document_id}_{user_query}"
        openai_cache_key = cache._generate_cache_key("openai", query_identifier)
        
        cached_response = await cache.get(openai_cache_key)
        if cached_response:
            logging.info(f"🚀 Retrieved OpenAI response from cache")
            cached_response["cached"] = True
            return cached_response
        
        search_client = request.app.state.search_client
        
        search_cache_key = cache._generate_cache_key("search",document_id)

        cached_search = await cache.get(search_cache_key)

        if cached_search:
            results = cached_search

        else:
            results = search_client.get_document(key = document_id)
            await cache.set(search_cache_key,dict(results),CACHE_TTL["search_results"])


        metadata = results.get("metadata", {})
        caption  = "|".join(metadata.get("captions", []))
        tags     = ", ".join(metadata.get("tags", []))
        text     = "\n".join(metadata.get("ocr_text", []))
        
        prompt = f"""
            You are an AI assistant analyzing visual content.

            Caption: {caption}
            Tags: {tags}
            Extracted Text:
            {text}

            User Query: {user_query}

            Please summarize what this image or document is about answer the query and suggest its potential purpose or category.
            Provide it over bullet list format using bold when appropriate.
            Provide elaborate and detailed response only when asked for it.
            """
        
        client =  AzureOpenAI(
            azure_endpoint=CONFIG['openai_endpoint'],
            api_key=CONFIG['openai_api_key'],
            api_version="2024-12-01-preview",
        )

        completion = client.chat.completions.create(
            model="gpt-35-turbo",
            messages=[
                {"role": "user", "content": prompt}
                ]
        )

        response_data = {
            "query": user_query,
            "caption": caption,
            "tags": tags,
            "ocr_text": text,
            "openai_response": completion.choices[0].message.content,
            "cached": False,
            "document_id": document_id
        }

        await cache.set(openai_cache_key,response_data,CACHE_TTL["openai_responses"])
        
        return response_data

    except Exception as e:
        raise HTTPException(
            status_code=500,
              detail=f"OpenAI processing failed: {str(e)}"
              )
    

@app.post("/general_chat/")
async def generate_general_response(request: Request, body:dict = Body(...)):
    user_query = body.get("query","")
    prompt = f"""
    You are an AI assistant replying to query

    user Query: {user_query}

    Give a relevant answer to the user query and lead them if they wanted any more assistance with.
"""
    client =  AzureOpenAI(
            azure_endpoint=CONFIG['openai_endpoint'],
            api_key=CONFIG['openai_api_key'],
            api_version="2024-12-01-preview",
        )

    completion = client.chat.completions.create(
       model="gpt-35-turbo",
        messages=[
            {"role": "user", "content": prompt}
            ]
        )
    
    response_data = {
        "query" :  user_query,
        "openai_response" : completion.choices[0].message.content
    }

    return response_data