cdn管理后台集成了阿里云、腾讯云、灵知开放平台、akamai

cdn刷新接口
使用方法
POST 接口： http://localhost/api/refresh_url
Content-Type: application/json
必填参数
JSON body 需要包含：

url：要刷新的完整 URL
timestamp：当前时间戳（秒）
signature：签名，计算方式见下方
签名生成规则

secret:cdn_manager_external_secret

签名计算方式：
message = url + timestamp
signature = hmac.sha256(secret, message).hexdigest()
