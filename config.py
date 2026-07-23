"""
统一配置管理
所有环境变量和配置项集中管理
"""
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""
    
    # ── COS 配置（必填） ──────────────────────────────────────────
    COS_SECRET_ID: str = ""
    COS_SECRET_KEY: str = ""
    COS_REGION: str = "ap-guangzhou"
    COS_BUCKET: str = ""
    
    # ── LLM 配置（可选） ──────────────────────────────────────────
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "claude-3-5-sonnet-20241022"
    LLM_API_URL: str = "https://api.anthropic.com/v1/messages"
    LLM_API_STYLE: str = "anthropic"  # "anthropic" 或 "openai"
    LLM_MAX_TOKENS: int = 1500
    API_TIMEOUT: int = 60
    
    # ── 服务配置 ──────────────────────────────────────────────────
    API_TOKEN: Optional[str] = None
    PRESIGN_EXPIRE: int = 3600
    PORT: int = 8080
    
    # ── AI 分析配置 ──────────────────────────────────────────────
    MAX_CHARS_PER_FILE: int = 3000
    MAX_TOTAL_CHARS: int = 15000
    
    # ── 路径配置 ──────────────────────────────────────────────────
    TEMPLATES_DIR: Path = Path(__file__).parent / "ai" / "templates"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


class PromptTemplate(BaseModel):
    """提示词模板"""
    name: str
    system_prompt: str
    default_user_prompt: str
    description: str = ""


class AnalysisTemplate(BaseModel):
    """分析模板"""
    id: str
    name: str
    description: str
    prompts: dict[str, PromptTemplate]


def load_templates(templates_dir: Path) -> dict[str, PromptTemplate]:
    """从模板目录加载提示词模板"""
    templates = {}
    
    if not templates_dir.exists():
        return templates
    
    # 加载所有 .txt 文件作为提示词模板
    for txt_file in templates_dir.glob("*.txt"):
        try:
            content = txt_file.read_text(encoding="utf-8")
            # 假设格式为：第一行是名称，第二行是描述，空行后是内容
            lines = content.strip().split("\n")
            if len(lines) >= 2:
                name = lines[0].strip()
                description = lines[1].strip() if len(lines) > 1 else ""
                # 空行后是系统提示词
                content_start = 2
                while content_start < len(lines) and not lines[content_start].strip():
                    content_start += 1
                system_prompt = "\n".join(lines[content_start:])
            else:
                name = txt_file.stem
                description = ""
                system_prompt = content
            
            templates[txt_file.stem] = PromptTemplate(
                name=name,
                system_prompt=system_prompt,
                default_user_prompt="",
                description=description
            )
        except Exception:
            continue
    
    return templates


# 全局配置实例
settings = Settings()

# 加载模板
templates = load_templates(settings.TEMPLATES_DIR) if settings.TEMPLATES_DIR.exists() else {}
