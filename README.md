# BurnCloud GCP Passthrough Proxy

这是一个轻量级的 Python 代理服务，用于实现 Google Vertex AI (Veo, Gemini) 的安全透传。

## 核心功能
1.  **鉴权 (Auth)**: 验证 BurnCloud 客户的 API Key (`sk-client-xxx`)。
2.  **自动签名**: 使用服务器端的 `vertex_creds.json` 自动生成并刷新 Google Access Token。
3.  **透传 (Pass-through)**: 将客户的请求体原封不动转发给 Google Vertex AI，并将结果原样返回。
4.  **审计 (Auditing)**: 记录所有请求日志到 `audit.log`。

## 部署指南 (给郑天锋)

### 1. 准备环境
```bash
cd burncloud-gcp-passthrough
pip install -r requirements.txt
```

### 2. 配置凭证
*   将 Google Service Account Key 重命名为 `vertex_creds.json` 并放入当前目录。
*   或者在 `main.py` 或环境变量中修改配置：
    ```bash
    export GCP_KEY_PATH="/path/to/your/key.json"
    export GCP_PROJECT_ID="your-real-project-id"
    export GCP_REGION="us-central1"
    ```

### 3. 启动服务
```bash
python main.py
```
服务将运行在 `http://0.0.0.0:8000`。

## API 调用示例 (给客户)

**Endpoint**: `http://api.burn.cloud/v1/vertex/veo-001-preview:predict`

**Headers**:
*   `Authorization`: `Bearer sk-client-veo-001`
*   `Content-Type`: `application/json`

**Body**: (直接使用 Google 官方格式)
```json
{
  "instances": [
    {
      "prompt": "A cinematic shot of a cyberpunk city..."
    }
  ],
  "parameters": {
    "sampleCount": 1
  }
}
```
