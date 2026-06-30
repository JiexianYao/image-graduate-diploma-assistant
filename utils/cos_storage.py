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
    cfg = CosConfig(
        Region=os.environ.get("COS_REGION", "ap-guangzhou"),
        SecretId=os.environ["COS_SECRET_ID"],
        SecretKey=os.environ["COS_SECRET_KEY"],
    )
    return CosS3Client(cfg), os.environ["COS_BUCKET"]


# ── 目录浏览 ───────────────────────────────────────────────────

def list_prefix(prefix: str) -> Dict:
    """
    列出 prefix 下的直接子目录（CommonPrefixes）和文件（Contents）。
    prefix 通常以 '/' 结尾，例如 '制度文档/' 或 ''（桶根）。
    """
    client, bucket = _cos()
    resp = client.list_objects(
        Bucket=bucket,
        Prefix=prefix,
        Delimiter="/",
        MaxKeys=500,
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
    return {"prefix": prefix, "folders": folders, "files": files}


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
