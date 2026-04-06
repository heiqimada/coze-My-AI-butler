"""
AI 状态管家 API 服务
支持 Coze + Supabase + 用户区分 + 对话记录
"""
import os
import logging
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_supabase()
    yield


app = FastAPI(title="AI状态管家 API", version="1.3.0", lifespan=lifespan)

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
    user_id: str = "guest"


class GoalCreate(BaseModel):
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    priority: str = "medium"


class StatusRecordCreate(BaseModel):
    status_type: str
    value: str
    note: Optional[str] = None


def coze_chat(message: str, user_id: str = "guest") -> str:
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
                            save_chat_record(user_id, message, msg["content"])
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


def save_chat_record(user_id: str, user_message: str, bot_response: str):
    if not supabase_client:
        return
    try:
        supabase_client.table("chat_records").insert({
            "user_id": user_id,
            "user_message": user_message,
            "bot_response": bot_response,
            "created_at": datetime.now().isoformat()
        }).execute()
    except Exception as e:
        logger.error(f"Save chat record error: {e}")


HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 状态管家</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F9FAFB; height: 100vh; display: flex; flex-direction: column; }
        .header { background: #FFF; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 18px; color: #1F2937; }
        .user-info { font-size: 12px; color: #6B7280; background: #F3F4F6; padding: 4px 12px; border-radius: 12px; }
        .chat { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
        .msg { max-width: 85%; padding: 12px 16px; border-radius: 16px; line-height: 1.5; word-break: break-word; }
        .msg.user { background: #4F46E5; color: #FFF; align-self: flex-end; border-bottom-right-radius: 4px; }
        .msg.bot { background: #FFF; color: #1F2937; align-self: flex-start; border-bottom-left-radius: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
        .msg.loading { color: #9CA3AF; }
        .welcome { text-align: center; padding: 60px 20px; }
        .welcome h2 { font-size: 24px; margin: 16px 0 8px; }
        .welcome p { color: #6B7280; }
        .input-area { background: #FFF; padding: 12px 16px; box-shadow: 0 -1px 3px rgba(0,0,0,0.1); }
        .input-row { display: flex; gap: 12px; }
        #msgInput { flex: 1; padding: 12px 16px; border-radius: 24px; border: 1px solid #E5E7EB; font-size: 16px; outline: none; }
        #msgInput:focus { border-color: #4F46E5; }
        .send-btn { padding: 12px 24px; background: #4F46E5; color: #FFF; border: none; border-radius: 24px; font-size: 16px; cursor: pointer; }
        .send-btn:disabled { background: #D1D5DB; cursor: not-allowed; }
        .quick { display: flex; gap: 8px; padding: 12px 16px; overflow-x: auto; }
        .quick button { flex-shrink: 0; padding: 8px 16px; border: 1px solid #E5E7EB; border-radius: 16px; background: #FFF; cursor: pointer; }
    </style>
</head>
<body>
    <div class="header">
        <h1>AI 状态管家</h1>
        <div class="user-info" id="userDisplay">用户: loading...</div>
    </div>
    <div class="chat" id="chatBox">
        <div class="welcome">
            <div style="font-size:64px">🤖</div>
            <h2>你好，我是你的 AI 状态管家</h2>
            <p>记录状态、设定目标，我来帮你分析和建议</p>
        </div>
    </div>
    <div class="quick">
        <button onclick="quickSend('今天感觉有点累')">😔 心情不好</button>
        <button onclick="quickSend('记录一下今天的睡眠')">😴 记录睡眠</button>
        <button onclick="quickSend('我想设定一个目标')">🎯 设定目标</button>
        <button onclick="quickSend('今天状态不错')">😊 状态不错</button>
    </div>
    <div class="input-area">
        <div class="input-row">
            <input type="text" id="msgInput" placeholder="输入消息..." onkeydown="handleKeyDown(event)">
            <button class="send-btn" id="sendBtn" onclick="sendMessage()">发送</button>
        </div>
    </div>
    <script>
        var currentUser = 'guest';
        var isLoading = false;
        
        function getUserFromURL() {
            var params = new URLSearchParams(window.location.search);
            return params.get('user') || 'guest';
        }
        
        currentUser = getUserFromURL();
        document.getElementById('userDisplay').textContent = '用户: ' + currentUser;
        
        if (currentUser === 'guest') {
            var name = prompt('请输入你的名字（用于区分不同用户的记录）：');
            if (name && name.trim()) {
                currentUser = name.trim().substring(0, 20);
                document.getElementById('userDisplay').textContent = '用户: ' + currentUser;
                var newUrl = window.location.pathname + '?user=' + encodeURIComponent(currentUser);
                window.history.replaceState({}, '', newUrl);
            }
        }
        
        async function sendMessage() {
            var input = document.getElementById('msgInput');
            var msg = input.value.trim();
            if (!msg || isLoading) return;
            
            addMessage(msg, 'user');
            input.value = '';
            
            var loadingId = addLoading();
            isLoading = true;
            document.getElementById('sendBtn').disabled = true;
            
            try {
                var response = await fetch('/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: msg, user_id: currentUser})
                });
                var data = await response.json();
                removeMessage(loadingId);
                if (data.success) {
                    addMessage(data.reply, 'bot');
                } else {
                    addMessage('抱歉发生了错误', 'bot');
                }
            } catch (e) {
                removeMessage(loadingId);
                addMessage('网络连接失败，请检查网络', 'bot');
            }
            
            isLoading = false;
            document.getElementById('sendBtn').disabled = false;
        }
        
        function quickSend(msg) {
            document.getElementById('msgInput').value = msg;
            sendMessage();
        }
        
        function handleKeyDown(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        }
        
        function addMessage(content, type) {
            var chatBox = document.getElementById('chatBox');
            var welcome = chatBox.querySelector('.welcome');
            if (welcome) welcome.remove();
            
            var div = document.createElement('div');
            div.className = 'msg ' + type;
            div.innerHTML = content.replace(/\\n/g, '<br>').replace(/\n/g, '<br>');
            chatBox.appendChild(div);
            chatBox.scrollTop = chatBox.scrollHeight;
        }
        
        function addLoading() {
            var id = 'loading-' + Date.now();
            var chatBox = document.getElementById('chatBox');
            var div = document.createElement('div');
            div.className = 'msg bot loading';
            div.id = id;
            div.textContent = '思考中...';
            chatBox.appendChild(div);
            chatBox.scrollTop = chatBox.scrollHeight;
            return id;
        }
        
        function removeMessage(id) {
            var el = document.getElementById(id);
            if (el) el.remove();
        }
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return HTML_PAGE


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat(), "coze_configured": bool(COZE_API_KEY), "supabase_configured": bool(supabase_client)}


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


@app.get("/chat/history")
async def get_chat_history(user_id: str = None, limit: int = 50):
    try:
        if not supabase_client:
            return {"success": False, "error": "Supabase not configured"}
        query = supabase_client.table("chat_records").select("*").order("created_at", desc=True).limit(limit)
        if user_id:
            query = query.eq("user_id", user_id)
        response = query.execute()
        return {"success": True, "data": response.data}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
