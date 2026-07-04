"""
研究生学位助手 v3 — FastAPI COS 代理

所有持久数据存储在腾讯云 COS；本服务是一个薄代理：
  • 列目录、生成预签名 URL
  • 上传/删除对象
  • AI 分析（读取 COS 对象文本 → LLM）
  • 创建虚拟目录（空占位对象）

所需环境变量：
    COS_SECRET_ID   COS_SECRET_KEY   COS_REGION   COS_BUCKET
可选：
    API_TOKEN          Bearer 鉴权令牌（留空则不鉴权）
    LLM_API_KEY        LLM 密钥
    LLM_API_BASE       LLM API 地址
    LLM_API_STYLE      anthropic | openai  （默认 anthropic）
    LLM_MODEL          模型名称
    PRESIGN_EXPIRE     预签名有效期（秒，默认 3600）
    PORT               监听端口（默认 8080）
"""

import io
import json
import os
import tempfile

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Security,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel  # used by AnalyzeRequest

from utils import (
    ai_call,
    delete_object,
    ensure_prefix,
    extract_text,
    get_object,
    list_prefix,
    presign_url,
    put_object,
    summarize_for_prompt,
)


# ── App ────────────────────────────────────────────────────────

app = FastAPI(title="研究生学位助手", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 鉴权（可选） ───────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)
_API_TOKEN = os.environ.get("API_TOKEN", "").strip()


def check_auth(creds: HTTPAuthorizationCredentials = Security(_bearer)):
    if not _API_TOKEN:
        return  # 不配置则不鉴权
    if creds is None or creds.credentials != _API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── 健康检查 ───────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"service": "研究生学位助手", "version": "3.0.0", "status": "ok"}


@app.get("/health/full")
def health_full():
    checks = {}
    # 测试 COS 连通性：列出桶根
    try:
        list_prefix("")
        checks["cos"] = "ok"
    except Exception as e:
        checks["cos"] = f"error: {e}"

    # 测试 LLM（只检查环境变量）
    checks["llm_key"] = "set" if os.environ.get("LLM_API_KEY") else "missing"

    ok = all(v in ("ok", "set") for v in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}


# ── 桶目录浏览 ─────────────────────────────────────────────────

@app.get("/browse")
def browse(
    prefix: str = Query("", description="桶前缀，如 '制度文档/' 或 ''（根）"),
    _: None = Depends(check_auth),
):
    """
    返回 prefix 下的直接子目录（folders）和文件（files）。
    前端懒加载：用户点击模块/目录时才调用此接口。
    """
    try:
        result = list_prefix(prefix)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"COS error: {e}")
    return result


# ── 预签名 URL ─────────────────────────────────────────────────

@app.get("/presign")
def presign(
    key: str = Query(..., description="对象键，如 '制度文档/student_handbook.pdf'"),
    expire: int = Query(
        int(os.environ.get("PRESIGN_EXPIRE", 3600)),
        description="URL 有效期（秒）",
    ),
    _: None = Depends(check_auth),
):
    """为指定对象生成临时读取 URL（默认 1 小时）"""
    try:
        url = presign_url(key, expire)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"COS error: {e}")
    return {"url": url, "key": key, "expire": expire}


# ── 文件上传 ───────────────────────────────────────────────────

@app.post("/upload", status_code=201)
async def upload(
    prefix: str = Query(..., description="目标前缀，如 '临时材料/'"),
    file: UploadFile = File(...),
    _: None = Depends(check_auth),
):
    """将文件上传到 COS，键 = prefix + 原始文件名"""
    if not prefix.endswith("/"):
        prefix += "/"
    key = prefix + file.filename
    data = await file.read()
    content_type = file.content_type or "application/octet-stream"
    try:
        put_object(key, data, content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"COS error: {e}")
    return {"key": key, "size": len(data), "name": file.filename}


# ── 创建虚拟目录 ───────────────────────────────────────────────

@app.post("/folder", status_code=201)
def create_folder(
    prefix: str = Query(..., description="新目录前缀，如 '期末复习/算法/'"),
    _: None = Depends(check_auth),
):
    """COS 没有真实目录，此接口上传空占位对象以创建虚拟目录"""
    try:
        key = ensure_prefix(prefix)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"COS error: {e}")
    return {"key": key}


# ── 删除对象 ───────────────────────────────────────────────────

@app.delete("/object")
def delete_obj(
    key: str = Query(..., description="对象键"),
    _: None = Depends(check_auth),
):
    try:
        delete_object(key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"COS error: {e}")
    return {"deleted": key}


# ── AI 分析 ───────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    key: str
    prompt: str = ""
    max_chars: int = 6000


@app.post("/ai/analyze")
def ai_analyze(body: AnalyzeRequest, _: None = Depends(check_auth)):
    """
    从 COS 下载对象，提取文本（PDF/图片），调用 LLM 生成分析。
    适用于：期末复习材料总结、制度文档要点提取等。
    """
    # 1. 下载对象
    try:
        data = get_object(body.key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"COS error: {e}")

    # 2. 提取文本
    filename = body.key.rsplit("/", 1)[-1].lower()
    if filename.endswith(".json"):
        try:
            text = json.dumps(json.loads(data), ensure_ascii=False)
        except Exception:
            text = data.decode("utf-8", errors="replace")
    elif filename.endswith((".pdf", ".png", ".jpg", ".jpeg", ".tiff")):
        tmp_ext = "." + filename.rsplit(".", 1)[-1]
        with tempfile.NamedTemporaryFile(suffix=tmp_ext, delete=False) as f:
            f.write(data)
            tmp_path = f.name
        try:
            raw_text = extract_text(tmp_path, max_chars=body.max_chars * 2)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        text = summarize_for_prompt(raw_text, max_chars=body.max_chars)
    else:
        text = data.decode("utf-8", errors="replace")[: body.max_chars]

    if not text.strip():
        raise HTTPException(status_code=422, detail="无法从该文件提取文本内容")

    # 3. 调用 LLM
    user_prompt = body.prompt or "请用中文对以下材料做简洁的要点总结，适合研究生复习备考。"
    api_key = os.environ.get("LLM_API_KEY")
    system_prompt = (
        "你是一名研究生学习助手，专门帮助中外合办项目的研究生理解学术和行政材料。"
        "回答简洁、结构清晰、使用中文。"
    )
    full_user = user_prompt + "\n\n---\n" + text

    try:
        result = ai_call(system_prompt, full_user, api_key=api_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    return {
        "key": body.key,
        "chars_analyzed": len(text),
        "analysis": result,
    }


# ── 启动入口 ───────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("index:app", host="0.0.0.0", port=port, reload=False)
