<details><summary>📄 点击展开 main.py 代码</summary>
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

# Supabase 配置 - 支持多种环境变量名
SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("COZE_SUPABASE_URL") or ""
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("COZE_SUPABASE_ANON_KEY") or ""
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("COZE_SUPABASE_SERVICE_ROLE_KEY") or ""

supabase_client: Optional[Client] = None


def init_supabase():
    """初始化 Supabase 客户端"""
    global supabase_client
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            logger.info(f"✅ Supabase 连接成功: {SUPABASE_URL[:30]}...")
        except Exception as e:
            logger.error(f"❌ Supabase 连接失败: {e}")
            supabase_client = None
    else:
        logger.warning("⚠️ Supabase 未配置")


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
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        result = response.json()

        if result.get("code") != 0:
            raise HTTPException(status_code=400, detail=result.get("msg", "API 调用失败"))

        chat_id = result["data"]["chat_id"]
        conversation_id = result["data"]["conversation_id"]

        retrieve_url = f"{COZE_API_BASE}/v3/chat/retrieve"
        for _ in range(120):
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
    """首页"""
    return {
        "name": "AI状态管家 API",
        "version": "1.1.0",
        "status": "running",
        "supabase_configured": bool(supabase_client),
        "endpoints": {
            "GET /health": "健康检查",
            "POST /chat": "与 AI 管家对话",
            "GET /goals": "获取目标列表",
            "POST /goals": "创建目标",
            "GET /status": "获取状态记录",
            "POST /status": "记录状态"
        }
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "coze_configured": bool(COZE_API_KEY),
        "supabase_configured": bool(supabase_client),
        "supabase_url": SUPABASE_URL[:40] + "..." if SUPABASE_URL else None,
        "service": "AI状态管家"
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    """与 AI 管家对话"""
    try:
        reply = coze_chat(request.message, request.user_id)
        return {
            "success": True,
            "reply": reply,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"聊天错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== 目标管理 API ==============
@app.get("/goals")
async def get_goals(limit: int = 20, offset: int = 0):
    """获取目标列表"""
    try:
        client = get_supabase()
        response = client.table("goals").select("*").order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        return {"success": True, "data": response.data, "count": len(response.data)}
    except Exception as e:
        logger.error(f"获取目标失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/goals")
async def create_goal(goal: GoalCreate):
    """创建目标"""
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
        logger.error(f"创建目标失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/goals/{goal_id}")
async def update_goal(goal_id: str, goal: GoalCreate):
    """更新目标"""
    try:
        client = get_supabase()
        data = {k: v for k, v in goal.model_dump().items() if v is not None}
        response = client.table("goals").update(data).eq("id", goal_id).execute()
        return {"success": True, "data": response.data[0] if response.data else None}
    except Exception as e:
        logger.error(f"更新目标失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/goals/{goal_id}")
async def delete_goal(goal_id: str):
    """删除目标"""
    try:
        client = get_supabase()
        client.table("goals").delete().eq("id", goal_id).execute()
        return {"success": True, "message": "目标已删除"}
    except Exception as e:
        logger.error(f"删除目标失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== 状态记录 API ==============
@app.get("/status")
async def get_status_records(limit: int = 20, offset: int = 0, status_type: Optional[str] = None):
    """获取状态记录"""
    try:
        client = get_supabase()
        query = client.table("status_records").select("*").order("created_at", desc=True).range(offset, offset + limit - 1)
        if status_type:
            query = query.eq("status_type", status_type)
        response = query.execute()
        return {"success": True, "data": response.data, "count": len(response.data)}
    except Exception as e:
        logger.error(f"获取状态记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/status")
async def create_status_record(record: StatusRecordCreate):
    """创建状态记录"""
    try:
        client = get_supabase()
        data = {
            "status_type": record.status_type,
            "value": record.value,
            "note": record.note
        }
        response = client.table("status_records").insert(data).execute()
        return {"success": True, "data": response.data[0]}
    except Exception as e:
        logger.error(f"创建状态记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== 启动 ==============
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)



</details>
