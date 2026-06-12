import json
from common import log
from alibabacloud_cdn20180510.client import Client as CdnClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_cdn20180510 import models as cdn_models
from Tea.core import TeaCore

def refresh_alicdn(domain, credentials, url=None):
    if not credentials.get('access_key') or not credentials.get('secret_key'):
        return {"success": False, "message": "请先配置阿里云 AccessKey 和 SecretKey", "provider": "alicdn"}

    access_key = credentials.get('access_key')
    secret_key = credentials.get('secret_key')
    if not access_key or not secret_key:
        return {"success": False, "message": "阿里云凭据不完整，需填写 AccessKey 和 SecretKey", "provider": "alicdn"}

    object_paths = [url] if url else [f"https://{domain}/"]

    if url and not url.endswith('/'):
        object_type = 'File'
    else:
        object_type = 'Directory'

    try:
        config = open_api_models.Config()
        # 您的AccessKey ID
        config.access_key_id = access_key
        # 您的AccessKey Secret
        config.access_key_secret = secret_key
        # 访问的域名
        config.endpoint = 'cdn.aliyuncs.com'
        client = CdnClient(config)

        request = cdn_models.RefreshObjectCachesRequest()
        request.set_ObjectPath(object_paths)
        request.set_ObjectType(object_type)

        response = client.refresh_object_caches(request)
        data = TeaCore.to_map(response)
        log(data)
        task_id = data.get('RefreshTaskId')
        if not task_id:
            return {"success": False, "message": "阿里云刷新请求提交成功，但未返回任务ID", "provider": "alicdn", "response": data}

        return {
            "success": True,
            "message": f"阿里云刷新请求已提交: {url or domain}, 任务ID={task_id}",
            "provider": "alicdn",
            "task_id": task_id,
            "refresh_status": "正在刷新"
        }
    except Exception as e:
        return {"success": False, "message": f"阿里云刷新请求异常: {e}", "provider": "alicdn"}


def check_alicdn_task(task_id, credentials):
    access_key = credentials.get('access_key')
    secret_key = credentials.get('secret_key')
    
    config = open_api_models.Config()
    # 您的AccessKey ID
    config.access_key_id = access_key
    # 您的AccessKey Secret
    config.access_key_secret = secret_key
    # 访问的域名
    config.endpoint = 'cdn.aliyuncs.com'
    client = CdnClient(config)

    request = cdn_models.DescribeRefreshTasksRequest()
    request.set_TaskId(task_id)

    response = client.describe_refresh_tasks_async(request)
    data = TeaCore.to_map(response)
    log(data)
    tasks = data.get('Tasks', {}).get('CDNTask', [])
    if not tasks:
        return {"success": False, "message": "未找到阿里云刷新任务", "provider": "alicdn"}
    task = tasks[0]
    return {
        "success": True,
        "provider": "alicdn",
        "task_status": task.get('Status'),
        "status_detail": task
    }
