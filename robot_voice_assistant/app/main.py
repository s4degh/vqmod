"""Voice-first animated robot assistant powered by a GapGPT-compatible API."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()
ROOT = Path(__file__).parent
STATIC = ROOT / "static"

app = FastAPI(title="Aegis Voice Robot")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SYSTEM_PROMPT = """You are Aegis, an impressive, calm robotic voice companion. Speak Persian unless the user asks otherwise. Your responses are intended for speech: answer naturally, clearly, and briefly (normally under 110 words). Never claim you performed web research unless supplied research notes. When you have research notes, cite the source URLs plainly in Persian at the end. Explain uncertainty honestly and avoid revealing private chain-of-thought; provide only a concise conclusion and useful rationale."""

class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=3000)
    history: list[Turn] = Field(default_factory=list, max_length=12)
    research: bool = False

class ChatResponse(BaseModel):
    answer: str
    researched: bool = False

async def research_web(query: str) -> str:
    """Return small, attributable research context when Tavily is configured."""
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return ""
    payload = {"api_key": key, "query": query, "search_depth": "basic", "max_results": 3}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post("https://api.tavily.com/search", json=payload)
        response.raise_for_status()
    results = response.json().get("results", [])
    return "\n\n".join(f"Source: {x.get('url')}\n{x.get('content', '')}" for x in results)

@app.get("/", include_in_schema=False)
async def homepage() -> FileResponse:
    return FileResponse(STATIC / "index.html")

@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    api_key = os.getenv("GAPGPT_API_KEY")
    if not api_key or api_key == "your_gapgpt_api_key":
        raise HTTPException(503, "GAPGPT_API_KEY is not configured on the server.")

    notes = ""
    if request.research:
        try:
            notes = await research_web(request.message)
        except httpx.HTTPError:
            notes = ""
    system = SYSTEM_PROMPT + (f"\n\nFresh research notes:\n{notes}" if notes else "")
    messages = [{"role": "system", "content": system}]
    messages.extend(x.model_dump() for x in request.history)
    messages.append({"role": "user", "content": request.message})
    base_url = os.getenv("GAPGPT_BASE_URL", "https://api.gapgpt.app/v1").rstrip("/")
    payload = {"model": os.getenv("GAPGPT_MODEL", "gpt-5.6"), "messages": messages, "temperature": 0.65}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{base_url}/chat/completions", json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "GapGPT did not return a usable response. Check API settings and model access.") from exc
    return ChatResponse(answer=answer, researched=bool(notes))
