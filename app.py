# Filename: backend.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Iterator, Optional
import json
import asyncio
import os
import toml
from typing import List, Dict, Tuple
from dataclasses import dataclass
from phi.agent import Agent
from phi.model.groq import Groq
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

# Contact information constants
SUPPORT_EMAIL = "info@s3ev.com"
SUPPORT_PHONE = "+91 63640 46550"

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")

@dataclass
class DocumentResponse:
    content: str
    confidence: float
    metadata: Dict

class Question(BaseModel):
    question: str

class VectorDBService:
    def __init__(self, api_url: str = None, api_key: str = None):
        try:
            if api_url and api_key:
                self.client = QdrantClient(url=api_url, api_key=api_key)
            else:
                self.client = QdrantClient(":memory:")
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            self.collection_name = "s3ev_full_data"
        except Exception as e:
            self.client = None
            self.model = None
            raise HTTPException(
                status_code=500,
                detail=f"Vector DB Initialization Error: {str(e)}"
            )
    
    def search(self, query: str, limit: int = 5) -> List[DocumentResponse]:
        if not self.client or not self.model:
            return []
        
        try:
            query_vector = self.model.encode(query).tolist()
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit
            )
            
            return [
                DocumentResponse(
                    content=result.payload.get('text', ''),
                    confidence=float(result.score),
                    metadata=result.payload.get('metadata', {})
                )
                for result in results
            ]
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Search Error: {str(e)}"
            )

class EVChargingExpertSystem:
    def __init__(self, config: Dict[str, str]):
        self.vector_db = VectorDBService(
            api_url=config.get("QDRANT_URL"),
            api_key=config.get("QDRANT_API_KEY")
        )
        self.model = Agent(
            model=Groq(id="llama-3.3-70b-versatile"),
            stream=True,
            description="EV charging solutions expert",
            instructions=[
                "Provide detailed technical information about EV charging infrastructure",
                "Explain charging standards (CCS, CHAdeMO, Tesla), power levels, and compatibility",
                "Discuss installation requirements and grid connectivity",
                "Offer troubleshooting for common charging issues",
                "Explain payment systems and roaming agreements",
                "Differentiate between documentation content and general knowledge"
            ]
        )
    
    async def process_query(self, query: str) -> Tuple[str, List[DocumentResponse]]:
        query_lower = query.lower()
        
        # Handle common greetings
        if any(greeting in query_lower for greeting in ['hi', 'hello', 'hey']):
            return (f"Hello! I'm EVCharge Assistant. How can I help with EV charging today?", [])
        
        # Handle technical queries
        if self.is_technical_query(query_lower):
            return await self.process_technical_query(query)
        
        # General queries
        return await self.process_general_query(query)

    def is_technical_query(self, query: str) -> bool:
        technical_keywords = [
            'charging station', 'connector', 'kw', 'charging speed',
            'installation', 'ccs', 'chademo', 'tesla', 'ocpp', 'power output',
            'load balancing', 'dynamic pricing', 'roaming'
        ]
        return any(kw in query for kw in technical_keywords)

    async def process_technical_query(self, query: str) -> Tuple[str, List[DocumentResponse]]:
        docs = self.vector_db.search(query)
        
        if not docs:
            return (await self.get_general_response(query), [])
        
        context = "\n".join([doc.content for doc in docs])
        response = await self.get_model_response(context, query)
        return response, docs

    async def process_general_query(self, query: str) -> Tuple[str, List[DocumentResponse]]:
        docs = self.vector_db.search(query)
        context = "\n".join([doc.content for doc in docs]) if docs else ""
        response = await self.get_model_response(context, query)
        return response, docs

    async def get_model_response(self, context: str, query: str) -> str:
        prompt = self.generate_prompt(context, query)
        return (await self.model.arun(prompt)).content

    def generate_prompt(self, context: str, query: str) -> str:
        base_template = f"""
        You are an expert EV charging solutions assistant. 
        {f"Reference documentation: {context}" if context else "Use general knowledge"}
        Current query: {query}
        
        Response requirements:
        - Be technically accurate but understandable
        - Include specifications when available
        - Mention compatibility considerations
        - Add safety recommendations where applicable
        - Conclude with support contact if technical
        
        Support contacts:
        Email: {SUPPORT_EMAIL}
        Phone: {SUPPORT_PHONE}
        """
        return base_template

    async def get_general_response(self, query: str) -> str:
        return f"""I'm an EV charging expert. While I don't have specific documentation on this, here's what I know:
        {query.capitalize()} in the context of EV charging typically involves... 
        For detailed technical support, contact {SUPPORT_EMAIL} or {SUPPORT_PHONE}."""

def load_config():
    config = {
        "QDRANT_URL": "http://localhost:6333",
        "QDRANT_API_KEY": ""
    }
    
    # Environment variables take priority
    for key in config:
        env_value = os.getenv(key)
        if env_value:
            config[key] = env_value
    
    # Fallback to secrets.toml
    if not config["QDRANT_URL"] or not config["QDRANT_API_KEY"]:
        try:
            with open("secrets.toml", "r") as f:
                toml_config = toml.load(f)
                config.update(toml_config)
        except FileNotFoundError:
            pass
    
    return config

# Initialize expert system
expert_system = EVChargingExpertSystem(load_config())

def create_sse_message(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"

async def stream_response(response: str) -> Iterator[str]:
    words = response.split()
    for word in words:
        message = create_sse_message({"token": word + " "})
        yield message
        await asyncio.sleep(0.05)

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/ask/stream")
async def stream_chat(question: Question):
    try:
        response, docs = await expert_system.process_query(question.question)
        
        return StreamingResponse(
            stream_response(response),
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
        
    except Exception as e:
        error_msg = create_sse_message({
            "error": f"Error processing query: {str(e)}"
        })
        return StreamingResponse(
            iter([error_msg]),
            headers={"Content-Type": "text/event-stream"}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
