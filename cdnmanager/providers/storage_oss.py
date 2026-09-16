import math

import oss2

from cdnmanager.common import UPLOAD_PART_SIZE, UPLOAD_PRESIGN_EXPIRES


def _endpoint(config):
    endpoint = (config.get('endpoint') or '').strip()
    if endpoint:
        return endpoint if endpoint.startswith('http') else f'https://{endpoint}'
    region = (config.get('region') or 'oss-cn-hangzhou').strip()
    return f'https://{region}.aliyuncs.com'


def _bucket_client(credential, config):
    auth = oss2.Auth(credential['access_key'], credential['secret_key'])
    return oss2.Bucket(auth, _endpoint(config), config['bucket'])


def presign_put(credential, config, object_key, mime=None):
    bucket = _bucket_client(credential, config)
    # 浏览器直传不在签名中绑定 Content-Type，减少 CORS 预检复杂度
    url = bucket.sign_url('PUT', object_key, UPLOAD_PRESIGN_EXPIRES)
    return url.replace('http://', 'https://') if url.startswith('http://') else url


def ensure_browser_cors(credential, config, allowed_origins=None):
    bucket = _bucket_client(credential, config)
    origins = allowed_origins or ['*']
    rule = oss2.models.CorsRule(
        allowed_origins=origins,
        allowed_methods=['GET', 'PUT', 'POST', 'HEAD', 'DELETE'],
        allowed_headers=['*'],
        expose_headers=['ETag', 'x-oss-request-id', 'Content-Length'],
        max_age_seconds=3600,
    )
    bucket.put_bucket_cors(oss2.models.BucketCors([rule]))


def init_multipart(credential, config, object_key, file_size, mime=None):
    bucket = _bucket_client(credential, config)
    headers = {}
    if mime:
        headers['Content-Type'] = mime
    upload_id = bucket.init_multipart_upload(object_key, headers=headers).upload_id
    total_parts = max(1, math.ceil(file_size / UPLOAD_PART_SIZE))
    parts = presign_parts(credential, config, object_key, upload_id, 1, min(total_parts, 20))
    return upload_id, parts, total_parts


def presign_parts(credential, config, object_key, upload_id, start_part, end_part):
    bucket = _bucket_client(credential, config)
    parts = []
    for part_number in range(start_part, end_part + 1):
        url = bucket.sign_url(
            'PUT',
            object_key,
            UPLOAD_PRESIGN_EXPIRES,
            params={'uploadId': upload_id, 'partNumber': str(part_number)},
        )
        if url.startswith('http://'):
            url = 'https://' + url[7:]
        parts.append({'part_number': part_number, 'url': url})
    return parts


def list_uploaded_parts(credential, config, object_key, upload_id):
    bucket = _bucket_client(credential, config)
    result = bucket.list_parts(object_key, upload_id)
    parts = []
    for part in result.parts:
        parts.append({
            'part_number': part.part_number,
            'etag': part.etag.strip('"') if part.etag else part.etag,
        })
    return sorted(parts, key=lambda item: item['part_number'])


def complete_multipart(credential, config, object_key, upload_id, parts):
    bucket = _bucket_client(credential, config)
    part_tags = sorted(
        [oss2.models.PartInfo(p['part_number'], p['etag']) for p in parts],
        key=lambda item: item.part_number,
    )
    result = bucket.complete_multipart_upload(object_key, upload_id, part_tags)
    etag = getattr(result, 'etag', None)
    return etag


def presign_get(credential, config, object_key):
    bucket = _bucket_client(credential, config)
    url = bucket.sign_url('GET', object_key, UPLOAD_PRESIGN_EXPIRES)
    return url.replace('http://', 'https://') if url.startswith('http://') else url


def list_objects(credential, config, prefix='', delimiter='/', max_keys=500):
    bucket = _bucket_client(credential, config)
    result = bucket.list_objects(prefix=prefix, delimiter=delimiter, max_keys=max_keys)
    folders = []
    files = []
    for folder in result.prefix_list or []:
        name = folder[len(prefix):].rstrip('/')
        if name:
            folders.append({'prefix': folder, 'name': name})
    for obj in result.object_list or []:
        if obj.key == prefix or obj.key.endswith('/'):
            continue
        name = obj.key[len(prefix):] if obj.key.startswith(prefix) else obj.key
        if not name or '/' in name.rstrip('/'):
            continue
        files.append({
            'key': obj.key,
            'name': name,
            'size': obj.size,
            'last_modified': obj.last_modified,
        })
    return {'prefix': prefix, 'folders': folders, 'files': files}


def delete_objects(credential, config, object_keys):
    bucket = _bucket_client(credential, config)
    if not object_keys:
        return 0
    bucket.batch_delete_objects(list(object_keys))
    return len(object_keys)


def delete_prefix(credential, config, prefix):
    bucket = _bucket_client(credential, config)
    deleted = 0
    for obj in oss2.ObjectIterator(bucket, prefix=prefix):
        bucket.delete_object(obj.key)
        deleted += 1
    return deleted


def verify_object(credential, config, object_key, expected_size):
    bucket = _bucket_client(credential, config)
    try:
        meta = bucket.head_object(object_key)
    except oss2.exceptions.NoSuchKey:
        return {'ok': False, 'error': '对象不存在'}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}
    actual_size = meta.content_length
    if expected_size is not None and actual_size != expected_size:
        return {'ok': False, 'error': f'大小不一致: 期望 {expected_size}, 实际 {actual_size}'}
    etag = meta.etag.strip('"') if meta.etag else None
    return {'ok': True, 'size': actual_size, 'etag': etag}
