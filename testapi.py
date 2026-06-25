import requests
import hmac
import hashlib
import time

secret = "e859e145390e2b8f8c7c5b4a71bd5b42f59914b64579fce7f9463e81dbf42524"
url = "http://cdn.blzb.gamegold.net.cn/mt_dev/"
timestamp = str(int(time.time()))
message = f"{url}{timestamp}".encode("utf-8")
signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
print(timestamp)
resp = requests.post(
    "http://cdnmanager.gamegold.net.cn/api/refresh_url",
    json={"url": url, "timestamp": timestamp, "signature": signature},
)
print(resp.status_code, resp.json())