"""
AI 状态管家 API 服务
独立部署版本，支持 Coze + Supabase 本地化
"""
import os
import logging
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_supabase()
    yield


app = FastAPI(title="AI状态管家 API", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

COZE_API_KEY = os.getenv("COZE_TOKEN") or os.getenv("COZE_API_KEY") or ""
COZE_BOT_ID = os.getenv("COZE_BOT_ID", "7624565645052756018")
COZE_API_BASE = os.getenv("COZE_API_BASE", "https://api.coze.cn")

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("COZE_SUPABASE_URL") or ""
SUPABASE_ANON = os.getenv("SUPABASE_ANON") or os.getenv("SUPABASE_KEY") or os.getenv("COZE_SUPABASE_ANON_KEY") or ""
SUPABASE_SERVICE = os.getenv("SUPABASE_SERVICE") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("COZE_SUPABASE_SERVICE_ROLE_KEY") or ""

supabase_client: Optional[Client] = None


def init_supabase():
    global supabase_client
    if SUPABASE_URL and SUPABASE_ANON:
        try:
            supabase_client = create_client(SUPABASE_URL, SUPABASE_ANON)
            logger.info("Supabase connected")
        except Exception as e:
            logger.error(f"Supabase error: {e}")
            supabase_client = None
    else:
        logger.warning("Supabase not configured")


def get_supabase() -> Client:
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    return supabase_client


class ChatRequest(BaseModel):
    message: str
    user_id: str = "web_user"


class GoalCreate(BaseModel):
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    priority: str = "medium"


class StatusRecordCreate(BaseModel):
    status_type: str
    value: str
    note: Optional[str] = None


def coze_chat(message: str, user_id: str = "web_user") -> str:
    if not COZE_API_KEY:
        raise HTTPException(status_code=500, detail="COZE_TOKEN not configured")

    url = f"{COZE_API_BASE}/v3/chat"
    headers = {
        "Authorization": f"Bearer {COZE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "bot_id": COZE_BOT_ID,
        "user_id": user_id,
        "stream": False,
        "auto_save_history": True,
        "additional_messages": [
            {"role": "user", "content": message, "content_type": "text"}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        result = response.json()

        if result.get("code") != 0:
            raise HTTPException(status_code=400, detail=result.get("msg", "API error"))

        chat_id = result["data"]["chat_id"]
        conversation_id = result["data"]["conversation_id"]

        for _ in range(120):
            retrieve_url = f"{COZE_API_BASE}/v3/chat/retrieve"
            retrieve_response = requests.get(
                retrieve_url, headers=headers,
                params={"chat_id": chat_id, "conversation_id": conversation_id}, timeout=30
            )
            retrieve_result = retrieve_response.json()

            if retrieve_result.get("code") != 0:
                raise HTTPException(status_code=400, detail=retrieve_result.get("msg"))

            status = retrieve_result["data"]["status"]
            if status == "completed":
                messages_url = f"{COZE_API_BASE}/v3/chat/message/list"
                messages_response = requests.get(
                    messages_url, headers=headers,
                    params={"chat_id": chat_id, "conversation_id": conversation_id}, timeout=30
                )
                messages_result = messages_response.json()

                if messages_result.get("code") == 0:
                    for msg in messages_result["data"]:
                        if msg["role"] == "assistant" and msg["type"] == "answer":
                            return msg["content"]
                return "Response empty"

            elif status == "failed":
                raise HTTPException(status_code=500, detail="Bot processing failed")

            import time
            time.sleep(1)

        raise HTTPException(status_code=504, detail="Timeout")

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Request timeout")
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {
        "name": "AI状态管家 API",
        "version": "1.1.0",
        "status": "running",
        "supabase_configured": bool(supabase_client)
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "coze_configured": bool(COZE_API_KEY),
        "supabase_configured": bool(supabase_client)
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        reply = coze_chat(request.message, request.user_id)
        return {"success": True, "reply": reply, "timestamp": datetime.now().isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/goals")
async def get_goals(limit: int = 20, offset: int = 0):
    try:
        client = get_supabase()
        response = client.table("goals").select("*").order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        return {"success": True, "data": response.data}
    except Exception as e:
        logger.error(f"Get goals error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/goals")
async def create_goal(goal: GoalCreate):
    try:
        client = get_supabase()
        data = {
            "title": goal.title,
            "description": goal.description,
            "deadline": goal.deadline,
            "priority": goal.priority,
            "status": "active"
        }
        response = client.table("goals").insert(data).execute()
        return {"success": True, "data": response.data[0]}
    except Exception as e:
        logger.error(f"Create goal error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status")
async def get_status_records(limit: int = 20, offset: int = 0, status_type: Optional[str] = None):
    try:
        client = get_supabase()
        query = client.table("status_records").select("*").order("created_at", desc=True).range(offset, offset + limit - 1)
        if status_type:
            query = query.eq("status_type", status_type)
        response = query.execute()
        return {"success": True, "data": response.data}
    except Exception as e:
        logger.error(f"Get status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/status")
async def create_status_record(record: StatusRecordCreate):
    try:
        client = get_supabase()
        data = {"status_type": record.status_type, "value": record.value, "note": record.note}
        response = client.table("status_records").insert(data).execute()
        return {"success": True, "data": response.data[0]}
    except Exception as e:
        logger.error(f"Create status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
