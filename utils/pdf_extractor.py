"""
PDF / 图片文本抽取工具
依赖 pymupdf（import fitz）

支持格式：
  - PDF → 直接抽取文字层
  - 图片（PNG/JPG/…）→ 使用 fitz 内置 OCR（需要 tesseract，可选）
  - 非 PDF/图片 → 返回空字符串，不报错
"""
from pathlib import Path
from typing import Optional

_SUPPORTED_PDF    = {".pdf"}
_SUPPORTED_IMAGE  = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff"}
_MAX_CHARS        = 12_000   # 截断阈值，避免超长文本撑爆 LLM context


def extract_text(file_path: Path, max_chars: int = _MAX_CHARS) -> str:
    """
    从文件中提取纯文本。
    返回字符串，失败时返回空字符串（不抛出异常）。
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        return ""

    suffix = file_path.suffix.lower()

    try:
        if suffix in _SUPPORTED_PDF:
            return _extract_pdf(file_path, fitz, max_chars)
        elif suffix in _SUPPORTED_IMAGE:
            return _extract_image(file_path, fitz, max_chars)
        else:
            return ""
    except Exception:
        return ""


def extract_text_from_data(data: bytes, filename: str, max_chars: int = _MAX_CHARS) -> str:
    """
    从内存数据中提取纯文本。
    支持 PDF、图片、JSON 和其他文本格式。
    返回字符串，失败时返回空字符串（不抛出异常）。
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        return ""

    suffix = Path(filename).suffix.lower()

    try:
        if suffix in _SUPPORTED_PDF:
            # 从内存数据提取 PDF 文本
            doc = fitz.open(stream=data, filetype="pdf")
            parts = []
            total = 0
            for page in doc:
                text = page.get_text("text")
                if total + len(text) > max_chars:
                    parts.append(text[: max_chars - total])
                    break
                parts.append(text)
                total += len(text)
            doc.close()
            return "\n".join(parts).strip()
        elif suffix in _SUPPORTED_IMAGE:
            # 从内存数据提取图片文本（OCR）
            doc = fitz.open(stream=data, filetype=suffix.lstrip("."))
            page = doc[0]
            tp = page.get_textpage_ocr(flags=3, language="chi_sim+eng")
            text = page.get_text(textpage=tp)
            doc.close()
            return text[:max_chars].strip()
        else:
            return ""
    except Exception:
        return ""


def _extract_pdf(path: Path, fitz, max_chars: int) -> str:
    doc = fitz.open(str(path))
    parts = []
    total = 0
    for page in doc:
        text = page.get_text("text")
        if total + len(text) > max_chars:
            parts.append(text[: max_chars - total])
            break
        parts.append(text)
        total += len(text)
    doc.close()
    return "\n".join(parts).strip()


def _extract_image(path: Path, fitz, max_chars: int) -> str:
    """
    尝试用 pymupdf 内置 OCR（需要 tesseract）。
    若 OCR 不可用则返回空字符串。
    """
    try:
        doc = fitz.open(str(path))
        page = doc[0]
        tp = page.get_textpage_ocr(flags=3, language="chi_sim+eng")
        text = page.get_text(textpage=tp)
        doc.close()
        return text[:max_chars].strip()
    except Exception:
        return ""


def summarize_for_prompt(text: str, max_chars: int = 6000) -> str:
    """截断并标注，使其适合作为 LLM prompt 的一部分"""
    if not text:
        return "(文件内容不可读取)"
    if len(text) > max_chars:
        return text[:max_chars] + f"\n…（已截断，原文约 {len(text)} 字符）"
    return text
