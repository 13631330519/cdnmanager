import math

import oss2

from common import UPLOAD_PART_SIZE, UPLOAD_PRESIGN_EXPIRES


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
    headers = {}
    if mime:
        headers['Content-Type'] = mime
    url = bucket.sign_url('PUT', object_key, UPLOAD_PRESIGN_EXPIRES, headers=headers)
    return url.replace('http://', 'https://') if url.startswith('http://') else url


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


def complete_multipart(credential, config, object_key, upload_id, parts):
    bucket = _bucket_client(credential, config)
    part_tags = sorted(
        [oss2.models.PartInfo(p['part_number'], p['etag']) for p in parts],
        key=lambda item: item.part_number,
    )
    result = bucket.complete_multipart_upload(object_key, upload_id, part_tags)
    etag = getattr(result, 'etag', None)
    return etag


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
