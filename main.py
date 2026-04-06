"""
AI 状态管家 API 服务 v1.3.1
支持 Coze + Supabase + 用户区分
"""
import os
import logging
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

supabase_client: Optional[Client] = None


def init_supabase():
    global supabase_client
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("COZE_SUPABASE_URL") or ""
    supabase_key = os.getenv("SUPABASE_ANON") or os.getenv("SUPABASE_KEY") or os.getenv("COZE_SUPABASE_ANON_KEY") or ""
    if supabase_url and supabase_key:
        try:
            supabase_client = create_client(supabase_url, supabase_key)
            logger.info("Supabase connected")
        except Exception as e:
            logger.error(f"Supabase error: {e}")


def get_supabase():
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    return supabase_client


class ChatRequest(BaseModel):
    message: str
    user_id: str = "guest"


def coze_chat(message: str, user_id: str = "guest") -> str:
    api_key = os.getenv("COZE_TOKEN") or os.getenv("COZE_API_KEY") or ""
    bot_id = os.getenv("COZE_BOT_ID", "7624565645052756018")
    api_base = os.getenv("COZE_API_BASE", "https://api.coze.cn")
    
    if not api_key:
        raise HTTPException(status_code=500, detail="COZE_TOKEN not configured")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "bot_id": bot_id,
        "user_id": user_id,
        "stream": False,
        "auto_save_history": True,
        "additional_messages": [{"role": "user", "content": message, "content_type": "text"}]
    }

    resp = requests.post(f"{api_base}/v3/chat", headers=headers, json=payload, timeout=120)
    result = resp.json()
    if result.get("code") != 0:
        raise HTTPException(status_code=400, detail=result.get("msg", "API error"))

    chat_id = result["data"]["chat_id"]
    conversation_id = result["data"]["conversation_id"]

    for _ in range(120):
        resp = requests.get(f"{api_base}/v3/chat/retrieve", headers=headers,
                          params={"chat_id": chat_id, "conversation_id": conversation_id}, timeout=30)
        res = resp.json()
        if res.get("code") != 0:
            raise HTTPException(status_code=400, detail=res.get("msg"))
        
        if res["data"]["status"] == "completed":
            resp = requests.get(f"{api_base}/v3/chat/message/list", headers=headers,
                              params={"chat_id": chat_id, "conversation_id": conversation_id}, timeout=30)
            msgs = resp.json()
            if msgs.get("code") == 0:
                for msg in msgs["data"]:
                    if msg["role"] == "assistant" and msg["type"] == "answer":
                        save_record(user_id, message, msg["content"])
                        return msg["content"]
            return "Response empty"
        elif res["data"]["status"] == "failed":
            raise HTTPException(status_code=500, detail="Bot processing failed")
        import time
        time.sleep(1)
    raise HTTPException(status_code=504, detail="Timeout")


def save_record(user_id: str, user_msg: str, bot_resp: str):
    if not supabase_client:
        return
    try:
        supabase_client.table("chat_records").insert({
            "user_id": user_id,
            "user_message": user_msg,
            "bot_response": bot_resp,
            "created_at": datetime.now().isoformat()
        }).execute()
    except Exception as e:
        logger.error(f"Save error: {e}")


app = FastAPI(title="AI状态管家", version="1.3.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    init_supabase()


@app.get("/", response_class=HTMLResponse)
async def home():
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI状态管家</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#F9FAFB;height:100vh;display:flex;flex-direction:column}
.header{background:#FFF;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,0.1);display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:18px;color:#1F2937}
.user-info{font-size:12px;color:#6B7280;background:#F3F4F6;padding:4px 12px;border-radius:12px}
.chat{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:16px}
.msg{max-width:85%;padding:12px 16px;border-radius:16px;line-height:1.5;word-break:break-word}
.msg.user{background:#4F46E5;color:#FFF;align-self:flex-end;border-bottom-right-radius:4px}
.msg.bot{background:#FFF;color:#1F2937;align-self:flex-start;border-bottom-left-radius:4px;box-shadow:0 1px 2px rgba(0,0,0,0.05)}
.msg.loading{color:#9CA3AF}
.welcome{text-align:center;padding:60px 20px}
.welcome h2{font-size:24px;margin:16px 0 8px}
.welcome p{color:#6B7280}
.input-area{background:#FFF;padding:12px 16px;box-shadow:0 -1px 3px rgba(0,0,0,0.1)}
.input-row{display:flex;gap:12px}
#msgInput{flex:1;padding:12px 16px;border-radius:24px;border:1px solid #E5E7EB;font-size:16px;outline:none}
.send-btn{padding:12px 24px;background:#4F46E5;color:#FFF;border:none;border-radius:24px;font-size:16px;cursor:pointer}
.send-btn:disabled{background:#D1D5DB;cursor:not-allowed}
.quick{display:flex;gap:8px;padding:12px 16px;overflow-x:auto}
.quick button{flex-shrink:0;padding:8px 16px;border:1px solid #E5E7EB;border-radius:16px;background:#FFF;cursor:pointer}
</style>
</head>
<body>
<div class="header">
<h1>AI状态管家</h1>
<div class="user-info" id="userDisplay">用户:...</div>
</div>
<div class="chat" id="chatBox">
<div class="welcome">
<div style="font-size:64px">&#128579;</div>
<h2>你好，我是你的AI状态管家</h2>
<p>记录状态、设定目标，我来帮你分析和建议</p>
</div>
</div>
<div class="quick">
<button id="btn1">&#128532; 心情不好</button>
<button id="btn2">&#128564; 记录睡眠</button>
<button id="btn3">&#127468; 设定目标</button>
<button id="btn4">&#128578; 状态不错</button>
</div>
<div class="input-area">
<div class="input-row">
<input type="text" id="msgInput" placeholder="输入消息...">
<button class="send-btn" id="sendBtn">发送</button>
</div>
</div>
<script>
var currentUser = "guest";
var isLoading = false;

function initUser() {
    var params = location.search.substring(1).split("&");
    for (var i = 0; i < params.length; i++) {
        var pair = params[i].split("=");
        if (pair[0] === "user") {
            currentUser = decodeURIComponent(pair[1] || "guest");
            break;
        }
    }
    document.getElementById("userDisplay").textContent = "用户: " + currentUser;
    if (currentUser === "guest") {
        var name = prompt("请输入你的名字:");
        if (name && name.trim()) {
            currentUser = name.trim().substring(0, 20);
            document.getElementById("userDisplay").textContent = "用户: " + currentUser;
            history.replaceState({}, "", "?user=" + encodeURIComponent(currentUser));
        }
    }
}

function sendMessage() {
    var input = document.getElementById("msgInput");
    var msg = input.value.trim();
    if (!msg || isLoading) return;
    addMessage(msg, "user");
    input.value = "";
    var loadingId = addLoading();
    isLoading = true;
    document.getElementById("sendBtn").disabled = true;
    
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/chat", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onload = function() {
        removeMessage(loadingId);
        isLoading = false;
        document.getElementById("sendBtn").disabled = false;
        if (xhr.status === 200) {
            try {
                var data = JSON.parse(xhr.responseText);
                addMessage(data.success ? data.reply : "发生错误", "bot");
            } catch(e) {
                addMessage("解析失败", "bot");
            }
        } else {
            addMessage("请求失败", "bot");
        }
    };
    xhr.onerror = function() {
        removeMessage(loadingId);
        isLoading = false;
        document.getElementById("sendBtn").disabled = false;
        addMessage("网络错误", "bot");
    };
    xhr.send(JSON.stringify({message: msg, user_id: currentUser}));
}

function quickSend(text) {
    document.getElementById("msgInput").value = text;
    sendMessage();
}

function addMessage(content, type) {
    var box = document.getElementById("chatBox");
    var welcome = box.querySelector(".welcome");
    if (welcome) welcome.remove();
    var div = document.createElement("div");
    div.className = "msg " + type;
    div.innerHTML = content.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\\n/g, "<br>").replace(/\\r/g, "").replace(/\\t/g, " ").replace(/\\n/g, "<br>");
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
}

function addLoading() {
    var id = "loading-" + Date.now();
    var box = document.getElementById("chatBox");
    var div = document.createElement("div");
    div.className = "msg bot loading";
    div.id = id;
    div.textContent = "思考中...";
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    return id;
}

function removeMessage(id) {
    var el = document.getElementById(id);
    if (el) el.parentNode.removeChild(el);
}

document.getElementById("msgInput").onkeydown = function(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
};
document.getElementById("sendBtn").onclick = sendMessage;
document.getElementById("btn1").onclick = function() { quickSend("今天感觉有点累"); };
document.getElementById("btn2").onclick = function() { quickSend("记录一下今天的睡眠"); };
document.getElementById("btn3").onclick = function() { quickSend("我想设定一个目标"); };
document.getElementById("btn4").onclick = function() { quickSend("今天状态不错"); };

initUser();
</script>
</body>
</html>"""
    return html


@app.get("/health")
async def health():
    return {"status": "healthy", "time": datetime.now().isoformat()}


@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        reply = coze_chat(req.message, req.user_id)
        return {"success": True, "reply": reply, "time": datetime.now().isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history")
async def history(user_id: str = None, limit: int = 50):
    if not supabase_client:
        return {"success": False, "error": "no db"}
    try:
        q = supabase_client.table("chat_records").select("*").order("created_at", desc=True).limit(limit)
        if user_id:
            q = q.eq("user_id", user_id)
        return {"success": True, "data": q.execute().data}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
