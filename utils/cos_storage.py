"""
腾讯云 COS 对象存储封装
"目录" = 有 Delimiter='/' 的 CommonPrefix（前缀以 / 结尾）
"文件" = Contents 中不以 / 结尾的对象

环境变量：
    COS_SECRET_ID
    COS_SECRET_KEY
    COS_REGION     默认 ap-guangzhou
    COS_BUCKET
"""

import os
from functools import lru_cache
from typing import Dict, List

from qcloud_cos import CosConfig, CosS3Client


@lru_cache(maxsize=1)
def _cos():
    """懒初始化，进程内缓存一个 (client, bucket) 元组"""
    # 检查必要的环境变量
    required_vars = ["COS_SECRET_ID", "COS_SECRET_KEY", "COS_BUCKET"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        raise EnvironmentError(
            f"缺少必要的COS环境变量: {', '.join(missing_vars)}。"
            "请检查容器环境变量配置并重启服务。"
        )
    
    cfg = CosConfig(
        Region=os.environ.get("COS_REGION", "ap-guangzhou"),
        SecretId=os.environ["COS_SECRET_ID"],
        SecretKey=os.environ["COS_SECRET_KEY"],
    )
    bucket = os.environ["COS_BUCKET"].strip("/")
    if not bucket:
        raise EnvironmentError("COS_BUCKET 不能为空")
    return CosS3Client(cfg), bucket


# ── 目录浏览 ───────────────────────────────────────────────────

def list_prefix(prefix: str, marker: str = "", max_keys: int = 500) -> Dict:
    """
    列出 prefix 下的直接子目录（CommonPrefixes）和文件（Contents）。
    prefix 通常以 '/' 结尾，例如 '制度文档/' 或 ''（桶根）。

    marker/max_keys 用于翻页：目录超过 max_keys 项时 COS 会截断结果，
    之前这里硬编码 MaxKeys=500 又不处理 IsTruncated/NextMarker，
    超过 500 项的目录会被静默截断且前端毫无感知。现在把这两个字段透出，
    调用方（/browse）可以把 marker 原样传回来翻下一页。
    """
    client, bucket = _cos()
    resp = client.list_objects(
        Bucket=bucket,
        Prefix=prefix,
        Delimiter="/",
        Marker=marker,
        MaxKeys=max_keys,
    )
    folders: List[Dict] = [
        {
            "key":  cp["Prefix"],
            "name": cp["Prefix"][len(prefix):].rstrip("/"),
            "type": "folder",
        }
        for cp in resp.get("CommonPrefixes", [])
    ]
    files: List[Dict] = [
        {
            "key":          obj["Key"],
            "name":         obj["Key"][len(prefix):],
            "size":         int(obj["Size"]),
            "lastModified": obj["LastModified"],
            "type":         "file",
        }
        for obj in resp.get("Contents", [])
        # 过滤掉前缀本身（空占位对象）和以 / 结尾的目录占位
        if obj["Key"] != prefix and not obj["Key"].endswith("/")
    ]
    is_truncated = str(resp.get("IsTruncated", "false")).lower() == "true"
    return {
        "prefix": prefix,
        "folders": folders,
        "files": files,
        "isTruncated": is_truncated,
        "nextMarker": resp.get("NextMarker", "") if is_truncated else "",
    }


# ── 递归列出所有文件 ───────────────────────────────────────────

def list_all_files(prefix: str) -> List[Dict]:
    """
    递归列出 prefix 下所有文件（包括子目录中的文件）。
    返回扁平化的文件列表。
    """
    files: List[Dict] = []
    
    def _recurse(current_prefix: str):
        result = list_prefix(current_prefix)
        files.extend(result["files"])
        
        # 递归进入子目录
        for folder in result["folders"]:
            _recurse(folder["key"])
    
    _recurse(prefix)
    return files


# ── 预签名 URL ─────────────────────────────────────────────────

def presign_url(key: str, expire: int = 3600) -> str:
    """生成 GET 预签名 URL，默认 1 小时有效"""
    client, bucket = _cos()
    return client.get_presigned_url(
        Method="GET",
        Bucket=bucket,
        Key=key,
        Expired=expire,
    )


# ── 对象读写删 ─────────────────────────────────────────────────

def put_object(key: str, data: bytes,
               content_type: str = "application/octet-stream") -> None:
    client, bucket = _cos()
    client.put_object(
        Bucket=bucket,
        Body=data,
        Key=key,
        ContentType=content_type,
    )


def get_object(key: str) -> bytes:
    client, bucket = _cos()
    resp = client.get_object(Bucket=bucket, Key=key)
    return resp["Body"].get_raw_stream().read()


def delete_object(key: str) -> None:
    client, bucket = _cos()
    client.delete_object(Bucket=bucket, Key=key)


# ── 目录创建（空占位） ─────────────────────────────────────────

def ensure_prefix(prefix: str) -> str:
    """
    确保一个前缀（目录）存在。
    COS 没有真实文件夹，上传一个以 / 结尾的空对象即可。
    返回规范化后的 prefix（保证以 / 结尾）。
    """
    key = prefix if prefix.endswith("/") else prefix + "/"
    put_object(key, b"", "application/x-directory")
    return key
