"""
冒烟测试 v3 — COS 代理 API
服务需已启动且 COS 环境变量已配置。

用法：
    python smoke_test.py [base_url]
    python smoke_test.py http://localhost:9001
"""
import io
import sys
import json
import requests

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:9001"
OK   = "\033[32m[OK]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"
SKIP = "\033[33m[SKIP]\033[0m"

def check(name: str, cond: bool, detail: str = ""):
    tag = OK if cond else FAIL
    print(f"  {tag} {name}" + (f"  →  {detail}" if detail else ""))
    return cond

def get(path, **kw):    return requests.get(BASE + path, timeout=10, **kw)
def post(path, **kw):   return requests.post(BASE + path, timeout=15, **kw)
def put(path, **kw):    return requests.put(BASE + path, timeout=10, **kw)
def delete(path, **kw): return requests.delete(BASE + path, timeout=10, **kw)

print(f"\n=== 研究生学位助手 v3 冒烟测试  [{BASE}] ===\n")
results = []

# ── 健康检查 ────────────────────────────────────────────────────
r = get("/health")
results.append(check("GET /health", r.status_code == 200, r.json().get("version", "")))

r = get("/health/full")
body = r.json()
results.append(check("GET /health/full", r.status_code == 200,
                      "cos=" + body.get("checks", {}).get("cos", "?")))

# ── 桶浏览（根） ────────────────────────────────────────────────
r = get("/browse", params={"prefix": ""})
ok = r.status_code == 200
body = r.json() if ok else {}
results.append(check("GET /browse (根)", ok,
                      f"folders={len(body.get('folders',[]))} files={len(body.get('files',[]))}"))

# ── 模块前缀浏览 ────────────────────────────────────────────────
for mod in ["制度文档/", "学分计算/", "期末复习/", "临时材料/"]:
    r = get("/browse", params={"prefix": mod})
    results.append(check(f"GET /browse ({mod})", r.status_code == 200))

# ── 上传测试文件 ────────────────────────────────────────────────
TEST_KEY = "临时材料/_smoke_test.txt"
TEST_PREFIX = "临时材料/"
fake_txt = b"smoke test content"
r = post("/upload", params={"prefix": TEST_PREFIX},
         files={"file": ("_smoke_test.txt", io.BytesIO(fake_txt), "text/plain")})
results.append(check("POST /upload", r.status_code == 201,
                      r.json().get("key", "") if r.status_code == 201 else r.text))

# ── 预签名 URL ──────────────────────────────────────────────────
r = get("/presign", params={"key": TEST_KEY})
has_url = r.status_code == 200 and r.json().get("url", "").startswith("http")
results.append(check("GET /presign", has_url))

# ── 新建目录 ────────────────────────────────────────────────────
TEST_DIR = "临时材料/_smoke_dir/"
r = post("/folder", params={"prefix": TEST_DIR})
results.append(check("POST /folder", r.status_code == 201,
                      r.json().get("key", "") if r.status_code == 201 else r.text))

# ── JSON 读写 ───────────────────────────────────────────────────
JSON_KEY = "学分计算/_smoke_test.json"
payload = {"semester": "测试学期", "courses": [{"name": "Test", "credits": 3,
           "assignments": [{"name": "期末", "weight": 100, "score": 85}]}]}
r = put("/json", json={"key": JSON_KEY, "data": payload})
results.append(check("PUT /json", r.status_code == 200,
                      f"size={r.json().get('size','?')}b" if r.status_code==200 else r.text))

r = get("/json", params={"key": JSON_KEY})
ok = r.status_code == 200 and r.json().get("semester") == "测试学期"
results.append(check("GET /json", ok))

# ── 删除测试对象 ────────────────────────────────────────────────
for key in [TEST_KEY, TEST_DIR, JSON_KEY]:
    r = delete("/object", params={"key": key})
    results.append(check(f"DELETE /object ({key.split('/')[-1] or key.split('/')[-2]})",
                          r.status_code == 200))

# ── 汇总 ────────────────────────────────────────────────────────
print()
passed = sum(results)
total  = len(results)
print("=" * 50)
print(f"结果：{passed}/{total} 通过" + (" ✓" if passed == total else " — 有失败项"))
if passed < total:
    sys.exit(1)
