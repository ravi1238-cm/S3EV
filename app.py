from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Iterator, Optional, List, Dict, Tuple
from dataclasses import dataclass
import json
import asyncio
import os
import logging
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
import concurrent.futures
from functools import lru_cache

# Logger Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
QDRANT_URL = "https://b39465e0-b4f9-4cca-a506-758a56dde755.us-east4-0.gcp.cloud.qdrant.io"
QDRANT_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwiZXhwIjoxNzQ2OTYyODY5fQ.QLWb9nZTmZTBibfqb5lyGzpZlC5j-GwubweA6yDJAu4"  # Replace this with your actual API key
COLLECTION_NAME = "s3ev_products_and_services"
SUPPORT_EMAIL = "support@s3ev.com"
SUPPORT_PHONE = "+91 63640 46550"
STREAM_DELAY = 0.02  # Reduced streaming delay
SEARCH_LIMIT = 3  # Reduced search limit for faster results

# FastAPI App
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@dataclass
class DocumentResponse:
    content: str
    confidence: float
    metadata: Dict
    is_product_info: bool = False

class Question(BaseModel):
    question: str

# Cache the embedding model for performance
@lru_cache(maxsize=1)
def get_embedding_model():
    return SentenceTransformer('all-MiniLM-L6-v2')

class VectorDBService:
    def __init__(self):
        try:
            self.client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
            self.model = get_embedding_model()
            self.collection_name = COLLECTION_NAME
            self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

            # Check if the collection exists
            collections = self.client.get_collections()
            if COLLECTION_NAME not in [col.name for col in collections.collections]:
                logger.error(f"Collection '{COLLECTION_NAME}' not found in Qdrant!")
                raise ValueError(f"Collection '{COLLECTION_NAME}' does not exist.")

            logger.info("Successfully connected to Qdrant.")
        except Exception as e:
            logger.error(f"Error initializing Qdrant client: {str(e)}")
            raise RuntimeError(f"Failed to connect to Qdrant: {str(e)}")

    async def search(self, query: str, limit: int = SEARCH_LIMIT) -> List[DocumentResponse]:
        try:
            loop = asyncio.get_running_loop()
            query_vector = await loop.run_in_executor(
                self.executor, lambda: self.model.encode(query).tolist()
            )
            
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                score_threshold=0.7
            )

            if not results:
                logger.warning("No search results found for the query.")

            return [
                DocumentResponse(
                    content=result.payload.get('text', ''),
                    confidence=float(result.score),
                    metadata=result.payload.get('metadata', {}),
                    is_product_info='product' in result.payload.get('metadata', {}).get('type', '').lower()
                )
                for result in results
            ]
        except Exception as e:
            logger.error(f"Search Error: {str(e)}")
            return []

def create_sse_message(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"

async def stream_response(response: str) -> Iterator[str]:
    chunk_size = 5
    words = response.split()
    chunks = [' '.join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    
    for chunk in chunks:
        message = create_sse_message({"token": chunk + " "})
        yield message
        await asyncio.sleep(STREAM_DELAY)

class EVChargingExpertSystem:
    def __init__(self):
        self.vector_db = VectorDBService()

    async def process_query(self, query: str) -> Tuple[str, List[DocumentResponse]]:
        docs = await self.vector_db.search(query)
        if not docs:
            return self.get_no_products_message(), []
        
        context = "\n".join([doc.content for doc in docs])
        response = await self.get_model_response(context, query)
        return response, docs

    async def get_model_response(self, context: str, query: str) -> str:
        prompt = f"Context:\n{context}\n\nProvide a concise response about {query}."
        # Implement the response generation using your AI model here, or replace it with another AI solution
        return f"Generated response for query: {query}"

    def get_no_products_message(self) -> str:
        return f"No specific product information found. Contact {SUPPORT_EMAIL} for details."

# Initialize expert system
expert_system = EVChargingExpertSystem()

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/ask/stream")
async def stream_chat(question: Question):
    try:
        response, _ = await expert_system.process_query(question.question)
        return StreamingResponse(
            stream_response(response),
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
    except Exception as e:
        logger.error(f"Error in stream_chat: {str(e)}")
        return StreamingResponse(
            iter([create_sse_message({"error": "An error occurred processing your request"})]),
            headers={"Content-Type": "text/event-stream"}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
