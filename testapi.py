import requests
import hmac
import hashlib
import time

secret = "cdn_manager_external_secret"
url = "https://test.domain.com/test.jpg"
timestamp = str(int(time.time()))
message = f"{url}{timestamp}".encode("utf-8")
signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
print(timestamp)
resp = requests.post(
    "http://localhost/api/refresh_url",
    json={"url": url, "timestamp": timestamp, "signature": signature},
)
print(resp.status_code, resp.json())