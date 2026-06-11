
import requests
import json
import base64
from akamai.edgegrid import EdgeGridAuth

from common import log


def refresh_akamai(domain, credentials, url=None):
    if not credentials.get('access_key') or not credentials.get('secret_key'):
        return {"success": False, "message": "请先配置 Akamai AccessKey 和 SecretKey", "provider": "akamai"}

    access_token = credentials.get('access_key')
    client_secret = credentials.get('secret_key')
    client_token = credentials.get('access_token',"akab-owtjys4qda7cyt72-utnls7273hnveyb2")
    
    if not client_token or not client_secret or not access_token:
        return {"success": False, "message": "Akamai凭据不完整，需填写 client_token 和 client_secret", "provider": "akamai"}

    purge_urls = [url] if url else [f"https://{domain}/", f"http://{domain}/"]
    if not purge_urls:
        log("No URLs to purge.")
        return

    # Akamai Fast Purge API v3 端点
    api_endpoint = f"https://akab-bvrty4llf7emi3cx-q5b27ednbqdbnoha.luna.akamaiapis.net/ccu/v3/invalidate/url/production"
    
    # 构建请求体
    payload = {
        "objects": purge_urls
    }

    try:
        # 使用 EdgeGridAuth 进行自动签名
        auth = EdgeGridAuth(
            client_token=client_token,
            client_secret=client_secret,
            access_token=access_token
        )

        headers = {'Content-Type': 'application/json'}
        
        response = requests.post(api_endpoint, json=payload, auth=auth, headers=headers)
        # 检查响应
        if response.status_code == 201:
            return {"success": True, "message": f"Akamai CDN刷新请求已提交: {domain}", "provider": "akamai"}

        log(response)
        return {"success": False, "message": f"Akamai CDN刷新请求失败: {domain}", "provider": "akamai"}
            
    except Exception as e:
        log(e)
        return {"success": False, "message": f"Akamai CDN刷新请求失败: {domain}", "provider": "akamai"}
