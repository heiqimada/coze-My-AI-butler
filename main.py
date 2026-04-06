"""
AI 状态管家 API 服务
独立部署版本，支持 Coze + Supabase 本地化
"""
import os
import logging
from datetime import datetime
from typing import Optional, Dict, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from supabase import create_client, Client

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    init_supabase()
    yield


app = FastAPI(title="AI状态管家 API", version="1.1.0", lifespan=lifespan)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== 配置 ==============
COZE_API_KEY = os.getenv("COZE_TOKEN") or os.getenv("COZE_API_KEY") or ""
COZE_BOT_ID = os.getenv("COZE_BOT_ID", "7624565645052756018")
COZE_API_BASE = os.getenv("COZE_API_BASE", "https://api.coze.cn")

# Supabase 配置
SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("COZE_SUPABASE_URL") or ""
SUPABASE_ANON = os.getenv("SUPABASE_ANON") or os.getenv("SUPABASE_KEY") or os.getenv("COZE_SUPABASE_ANON_KEY") or ""
SUPABASE_SERVICE = os.getenv("SUPABASE_SERVICE") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("COZE_SUPABASE_SERVICE_ROLE_KEY") or ""

supabase_client: Optional[Client] = None


def init_supabase():
    """初始化 Supabase 客户端"""
    global supabase_client
    if SUPABASE_URL and SUPABASE_ANON:
        try:
            supabase_client = create_client(SUPABASE_URL, SUPABASE_ANON)
            logger.info(f"Supabase 连接成功: {SUPABASE_URL[:30]}...")
        except Exception as e:
            logger.error(f"Supabase 连接失败: {e}")
            supabase_client = None
    else:
        logger.warning("Supabase 未配置")


def get_supabase() -> Client:
    """获取 Supabase 客户端"""
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase 未配置或连接失败")
    return supabase_client


# ============== 数据模型 ==============
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


# ============== 辅助函数 ==============
def coze_chat(message: str, user_id: str = "web_user") -> str:
    """调用 Coze API 进行对话"""
    if not COZE_API_KEY:
        raise HTTPException(status_code=500, detail="COZE_TOKEN 未配置")

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
            raise HTTPException(status_code=400, detail=result.get("msg", "API 调用失败"))

        chat_id = result["data"]["chat_id"]
        conversation_id = result["data"]["conversation_id"]

        retrieve_url = f"{COZE_API_BASE}/v3/chat/retrieve"
        for _ in range(120):
            retrieve_response = requests.get(
                retr
