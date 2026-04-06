"""
AI 状态管家 API 服务
独立部署版本，使用 Coze API Key 直连
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI状态管家 API", version="1.0.0")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== 配置 ==============
COZE_API_KEY = os.getenv("COZE_API_KEY", "")
COZE_BOT_ID = os.getenv("COZE_BOT_ID", "7624565645052756018")
COZE_API_BASE = os.getenv("COZE_API_BASE", "https://api.coze.cn")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


# ============== 数据模型 ==============
class ChatRequest(BaseModel):
    message: str
    user_id: str = "web_user"


class GoalRequest(BaseModel):
    content: str
    category: str = "general"
    priority: str = "should_do"
    deadline: Optional[str] = None


class StatusRequest(BaseModel):
    content: str
    category: str = "general"
    mood_level: Optional[int] = None
    energy_level: Optional[int] = None
    tags: Optional[List[str]] = None


# ============== 辅助函数 ==============
def get_supabase_headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }


def coze_chat(message: str, user_id: str = "web_user") -> str:
    if not COZE_API_KEY:
        raise HTTPException(status_code=500, detail="COZE_API_KEY 未配置")

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
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        result = response.json()

        if result.get("code") != 0:
            raise HTTPException(status_code=400, detail=result.get("msg", "API 调用失败"))

        chat_id = result["data"]["chat_id"]
        conversation_id = result["data"]["conversation_id"]

        retrieve_url = f"{COZE_API_BASE}/v3/chat/retrieve"
        for _ in range(60):
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
                return "回复获取成功，但内容为空"

            elif status == "failed":
                raise HTTPException(status_code=500, detail="Bot 处理失败")

            import time
            time.sleep(1)

        raise HTTPException(status_code=504, detail="处理超时")

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="请求超时")
    except requests.exceptions.RequestException as e:
        logger.error(f"请求错误: {e}")
        raise HTTPException(status_code=500, detail=f"网络错误: {str(e)}")


# ============== API 路由 ==============
@app.get("/")
async def root():
    return {
        "name": "AI状态管家 API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "GET /health": "健康检查",
            "POST /chat": "与 AI 管家对话"
        }
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "coze_configured": bool(COZE_API_KEY),
        "supabase_configured": bool(SUPABASE_URL)
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        reply = coze_chat(request.message, request.user_id)
        return {"success": True, "reply": reply, "timestamp": datetime.now().isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"聊天错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
