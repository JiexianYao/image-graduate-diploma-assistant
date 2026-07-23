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

import json
import os
from pathlib import Path
from typing import List, Optional

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
from pydantic import BaseModel, Field

from config import settings, templates, load_templates, PromptTemplate
from utils import (
    ai_call,
    delete_object,
    ensure_prefix,
    extract_text_from_data,
    get_object,
    list_all_files,
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


def check_auth(creds: HTTPAuthorizationCredentials = Security(_bearer)):
    if not settings.API_TOKEN:
        return  # 不配置则不鉴权
    if creds is None or creds.credentials != settings.API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── 健康检查 ───────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"service": "研究生学位助手", "version": "3.0.0", "status": "ok"}


@app.get("/health/full")
def health_full():
    checks = {}
    # 检查环境变量是否存在
    cos_vars = ["COS_SECRET_ID", "COS_SECRET_KEY", "COS_REGION", "COS_BUCKET"]
    for var in cos_vars:
        value = os.environ.get(var)
        if value:
            # 只显示部分值，避免泄露敏感信息
            if len(value) > 10:
                checks[var] = f"set ({value[:8]}...)"
            else:
                checks[var] = f"set ({value})"
        else:
            checks[var] = "missing"
    
    # 测试 COS 连通性：列出桶根
    try:
        list_prefix("")
        checks["cos"] = "ok"
    except Exception as e:
        checks["cos"] = f"error: {e}"

    # 测试 LLM（只检查环境变量）
    checks["llm_key"] = "set" if settings.LLM_API_KEY else "missing"

    ok = all(v in ("ok", "set") or not v.startswith("missing") for v in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}


# ── 模板管理 ───────────────────────────────────────────────────

@app.get("/ai/templates")
def list_templates():
    """列出所有可用的分析模板"""
    return {
        "templates": [
            {
                "id": t["id"],
                "name": t["name"],
                "description": t["description"],
                "default_prompt": t.get("default_prompt", "")
            }
            for t in templates.values()
        ]
    }


@app.post("/ai/templates/reload")
def reload_templates():
    """重新加载模板配置"""
    global templates
    templates = load_templates(settings.TEMPLATES_DIR)
    return {"status": "ok", "count": len(templates)}


# ── 桶目录浏览 ─────────────────────────────────────────────────

@app.get("/browse")
def browse(
    prefix: str = Query("", description="桶前缀，如 '制度文档/' 或 ''（根）"),
    marker: str = Query("", description="翻页标记，取上一页响应里的 nextMarker"),
    _: None = Depends(check_auth),
):
    """
    返回 prefix 下的直接子目录（folders）和文件（files）。
    前端懒加载：用户点击模块/目录时才调用此接口。
    单页最多 500 项；若 isTruncated=true，用响应里的 nextMarker 再调一次本接口翻页。
    """
    try:
        result = list_prefix(prefix, marker)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"COS error: {e}")
    return result


# ── 预签名 URL ─────────────────────────────────────────────────

@app.get("/presign")
def presign(
    key: str = Query(..., description="对象键，如 '制度文档/student_handbook.pdf'"),
    expire: int = Query(
        settings.PRESIGN_EXPIRE,
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


# ── 文本提取辅助函数 ───────────────────────────────────────────

def _extract_text_from_file(data: bytes, filename: str, max_chars: int) -> str:
    """从文件数据中提取文本"""
    filename_lower = filename.lower()
    
    if filename_lower.endswith(".json"):
        try:
            text = json.dumps(json.loads(data), ensure_ascii=False, indent=2)
        except Exception:
            text = data.decode("utf-8", errors="replace")
        return text[:max_chars]
    elif filename_lower.endswith((".pdf", ".png", ".jpg", ".jpeg", ".tiff")):
        raw_text = extract_text_from_data(data, filename, max_chars=max_chars * 2)
        return summarize_for_prompt(raw_text, max_chars=max_chars)
    else:
        return data.decode("utf-8", errors="replace")[:max_chars]


# ── AI 分析（统一端点） ───────────────────────────────────────

class AnalyzeRequest(BaseModel):
    """分析请求"""
    # 二选一：单文件分析或目录分析
    key: Optional[str] = Field(None, description="单个文件的 COS 对象键")
    directory: Optional[str] = Field(None, description="目录前缀，递归分析所有文件")
    
    # 分析配置
    prompt: str = Field("", description="自定义分析提示")
    template_id: Optional[str] = Field(None, description="使用预定义模板 ID")
    max_chars_per_file: int = Field(settings.MAX_CHARS_PER_FILE, description="每个文件最大字符数")
    max_total_chars: int = Field(settings.MAX_TOTAL_CHARS, description="目录分析时总字符数上限")


@app.post("/ai/analyze")
def ai_analyze(body: AnalyzeRequest, _: None = Depends(check_auth)):
    """
    统一的 AI 分析端点。
    
    支持两种模式：
    1. 单文件分析：传入 key 参数
    2. 目录分析：传入 directory 参数，递归分析所有文件
    
    使用 template_id 可以应用预定义的提示词模板。
    """
    # 验证参数：必须提供 key 或 directory 之一
    if not body.key and not body.directory:
        raise HTTPException(status_code=400, detail="必须提供 key 或 directory 参数之一")
    
    if body.key and body.directory:
        raise HTTPException(status_code=400, detail="不能同时提供 key 和 directory 参数")
    
    # 加载模板
    system_prompt = None
    default_user_prompt = None
    
    if body.template_id:
        if body.template_id not in templates:
            raise HTTPException(status_code=400, detail=f"模板 {body.template_id} 不存在")
        
        template = templates[body.template_id]
        system_prompt = template.system_prompt
        default_user_prompt = template.default_user_prompt
    
    # 默认系统提示词
    if not system_prompt:
        system_prompt = (
            "你是一名研究生学习助手，专门帮助中外合办项目的研究生理解学术和行政材料。"
            "回答简洁、结构清晰、使用中文。"
        )
    
    # 默认用户提示词
    user_prompt = body.prompt or default_user_prompt or "请用中文对以下材料做简洁的要点总结，适合研究生复习备考。"
    
    try:
        if body.key:
            # 单文件分析
            return _analyze_single_file(
                body.key, user_prompt, system_prompt,
                body.max_chars_per_file
            )
        else:
            # 目录分析
            return _analyze_directory(
                body.directory, user_prompt, system_prompt,
                body.max_chars_per_file, body.max_total_chars
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"分析失败: {e}")


def _analyze_single_file(
    key: str,
    user_prompt: str,
    system_prompt: str,
    max_chars: int
) -> dict:
    """单文件分析"""
    # 1. 下载对象
    try:
        data = get_object(key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"COS error: {e}")
    
    # 2. 提取文本
    filename = key.rsplit("/", 1)[-1]
    text = _extract_text_from_file(data, filename, max_chars)
    
    if not text.strip():
        raise HTTPException(status_code=422, detail="无法从该文件提取文本内容")
    
    # 3. 调用 LLM
    full_user = user_prompt + "\n\n---\n" + text
    
    try:
        result = ai_call(system_prompt, full_user, api_key=settings.LLM_API_KEY)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")
    
    return {
        "mode": "single_file",
        "key": key,
        "chars_analyzed": len(text),
        "analysis": result,
    }


def _analyze_directory(
    directory: str,
    user_prompt: str,
    system_prompt: str,
    max_chars_per_file: int,
    max_total_chars: int
) -> dict:
    """目录分析"""
    # 确保目录前缀以 / 结尾
    prefix = directory if directory.endswith("/") else directory + "/"
    
    # 1. 递归列出所有文件
    try:
        files = list_all_files(prefix)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"COS error: {e}")
    
    if not files:
        raise HTTPException(status_code=422, detail="目录为空或不存在")
    
    # 2. 批量提取文本
    texts = []
    total_chars = 0
    
    for file_info in files:
        if total_chars >= max_total_chars:
            break
        
        filename = file_info["name"]
        
        try:
            data = get_object(file_info["key"])
        except Exception:
            continue  # 跳过无法下载的文件
        
        # 提取文本
        text = _extract_text_from_file(data, filename, max_chars_per_file)
        
        if text.strip():
            texts.append(f"=== {file_info['name']} ===\n{text}\n")
            total_chars += len(text)
    
    if not texts:
        raise HTTPException(status_code=422, detail="无法从目录中提取文本内容")
    
    # 3. 汇总所有文本
    all_texts = "\n".join(texts)
    
    # 4. 调用 LLM 分析
    full_user = user_prompt + "\n\n---\n" + all_texts
    
    try:
        result = ai_call(system_prompt, full_user, api_key=settings.LLM_API_KEY)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")
    
    return {
        "mode": "directory",
        "directory": prefix,
        "files_analyzed": len(texts),
        "total_chars": total_chars,
        "analysis": result,
    }


# ── 启动入口 ───────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = settings.PORT
    uvicorn.run("index:app", host="0.0.0.0", port=port, reload=False)
