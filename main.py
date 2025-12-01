import os
import time
import json
import httpx
import logging
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from google.oauth2 import service_account
import google.auth.transport.requests

# --- Configuration ---
# 从环境变量读取，如果不存在则使用默认值（生产环境建议强制使用环境变量）
# 请将您的 Service Account JSON 文件重命名为 vertex_creds.json 并放在此目录下
KEY_PATH = os.getenv("GCP_KEY_PATH", "vertex_creds.json") 
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "your-project-id") # 替换为您的 GCP Project ID
REGION = os.getenv("GCP_REGION", "us-central1")

# 简单的 API Key 存储 (实际生产环境应替换为数据库查询)
# 格式: "sk-xxx": {"balance": 1000, "rpm_limit": 50}
VALID_API_KEYS = {
    "sk-client-veo-001": {"name": "VIP Client A", "active": True},
    "sk-burncloud-admin": {"name": "Admin Test", "active": True}
}

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("audit.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("burncloud-proxy")

app = FastAPI(title="BurnCloud GCP Passthrough Proxy")

# --- Google Auth Helper ---
class GoogleAuthManager:
    def __init__(self, key_path):
        if not os.path.exists(key_path):
            # 在启动时如果找不到 Key 仅警告，不 crash，方便测试
            logger.warning(f"GCP Credential file NOT found at: {key_path}. GCP calls will fail.")
            self.creds = None
        else:
            logger.info(f"Loading GCP credentials from {key_path}")
            self.creds = service_account.Credentials.from_service_account_file(
                key_path, 
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
            self.auth_req = google.auth.transport.requests.Request()

    def get_token(self):
        """获取有效的 Bearer Token，自动处理刷新"""
        if not self.creds:
             raise RuntimeError("GCP Credentials not initialized")
        
        if not self.creds.valid:
            logger.info("Refreshing GCP access token...")
            self.creds.refresh(self.auth_req)
        elif self.creds.expired:
             logger.info("GCP token expired, refreshing...")
             self.creds.refresh(self.auth_req)
        
        return self.creds.token

# 初始化 Auth Manager
auth_manager = GoogleAuthManager(KEY_PATH)

# --- Middleware / Dependency ---

async def verify_api_key(request: Request):
    """验证 BurnCloud 客户的 API Key"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    api_key = auth_header.split(" ")[1]
    
    if api_key not in VALID_API_KEYS:
        logger.warning(f"Unauthorized access attempt with key: {api_key[:8]}***")
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    if not VALID_API_KEYS[api_key]["active"]:
        raise HTTPException(status_code=403, detail="API Key is inactive")
        
    return api_key

# --- Routes ---

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "burncloud-gcp-proxy"}

@app.post("/v1/vertex/{model_name}:predict")
async def proxy_vertex_predict(
    model_name: str, 
    request: Request, 
    api_key: str = Depends(verify_api_key)
):
    """
    通用的 Vertex AI Predict 接口透传
    支持 Veo (Video), Gemini (Text/Multimodal) 等
    路径示例: /v1/vertex/veo-001-preview:predict
    """
    # 1. 获取客户原始请求体
    try:
        client_payload = await request.json()
    except json.JSONDecodeError:
         raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 2. 审计日志 (Shadow Auditing)
    # 注意：不要打印过大的 payload，这里只记录元数据
    logger.info(f"Proxying request for model: {model_name} by user: {VALID_API_KEYS[api_key]['name']}")
    
    # 3. 构造 Google 上游地址
    # 官方格式: https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{REGION}/publishers/google/models/{MODEL}:predict
    google_url = f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{REGION}/publishers/google/models/{model_name}:predict"
    
    # 4. 获取 GCP Token
    try:
        gcp_token = auth_manager.get_token()
    except Exception as e:
        logger.error(f"Token generation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error: GCP Auth Failed")

    # 5. 发送请求给 Google
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                google_url,
                json=client_payload,
                headers={
                    "Authorization": f"Bearer {gcp_token}",
                    "Content-Type": "application/json"
                },
                timeout=120.0 # 视频生成通常需要较长时间
            )
        except httpx.RequestError as exc:
            logger.error(f"Request to Google failed: {exc}")
            raise HTTPException(status_code=502, detail=f"Upstream connection failed: {str(exc)}")

    # 6. 记录响应状态
    logger.info(f"Google response status: {response.status_code}")
    if response.status_code >= 400:
        logger.error(f"Upstream Error Body: {response.text}")

    # 7. 透传响应
    # 使用 JSONResponse 确保 Content-Type 正确
    return JSONResponse(
        content=response.json(),
        status_code=response.status_code
    )

if __name__ == "__main__":
    import uvicorn
    print(f"Starting BurnCloud Proxy on port 8000...")
    print(f"Target GCP Project: {PROJECT_ID}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
