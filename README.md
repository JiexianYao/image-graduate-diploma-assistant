# 研究生学位助手 v3

基于 FastAPI 和腾讯云 COS 的研究生学位助手服务。

## 环境变量配置

### 快速开始

1. 复制环境变量模板：
   ```bash
   cp .env.example .env
   ```

2. 编辑 `.env` 文件，填写实际的配置值：
   ```bash
   # 必填项
   COS_SECRET_ID=your_actual_secret_id
   COS_SECRET_KEY=your_actual_secret_key
   COS_REGION=ap-guangzhou
   COS_BUCKET=your_actual_bucket_name
   
   # 可选项（如需 AI 分析功能）
   LLM_API_KEY=your_llm_api_key
   ```

3. 启动服务：
   ```bash
   docker-compose up -d
   ```

### 环境变量说明

#### 必填变量
| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `COS_SECRET_ID` | 腾讯云 COS 密钥 ID | `AKIDxxxxxxxxxxxxxxxx` |
| `COS_SECRET_KEY` | 腾讯云 COS 密钥 Key | `xxxxxxxxxxxxxxxxxxxxxxxx` |
| `COS_REGION` | COS 区域 | `ap-guangzhou` |
| `COS_BUCKET` | COS 存储桶名称 | `my-bucket` |

#### 可选变量
| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `LLM_API_KEY` | LLM API 密钥 | 空（不启用 AI 功能） |
| `LLM_MODEL` | LLM 模型名称 | `claude-3-5-sonnet-20241022` |
| `LLM_API_BASE` | LLM API 地址 | `https://api.anthropic.com` |
| `LLM_API_STYLE` | API 风格（anthropic/openai） | `anthropic` |
| `API_TOKEN` | API 鉴权令牌 | 空（不启用鉴权） |
| `PRESIGN_EXPIRE` | 预签名 URL 有效期（秒） | `3600` |
| `PORT` | 服务端口 | `8080` |

## 本地开发

### 安装依赖
```bash
pip install -r requirements.txt
```

### 设置环境变量

**Windows (PowerShell):**
```powershell
$env:COS_SECRET_ID="your_value"
$env:COS_SECRET_KEY="your_value"
$env:COS_BUCKET="your_value"
```

**Linux/macOS:**
```bash
export COS_SECRET_ID="your_value"
export COS_SECRET_KEY="your_value"
export COS_BUCKET="your_value"
```

### 运行服务
```bash
python index.py
```

## API 文档

启动服务后访问：`http://localhost:8080/docs`

## 健康检查

- 基础健康检查：`GET /health`
- 完整健康检查：`GET /health/full`