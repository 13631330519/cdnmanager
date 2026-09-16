import math

from qcloud_cos import CosConfig, CosS3Client

from common import UPLOAD_PART_SIZE, UPLOAD_PRESIGN_EXPIRES


def _client(credential, config):
    region = (config.get('region') or 'ap-guangzhou').strip()
    scheme = 'https'
    config_obj = CosConfig(
        Region=region,
        SecretId=credential['access_key'],
        SecretKey=credential['secret_key'],
        Scheme=scheme,
    )
    return CosS3Client(config_obj), region


def presign_put(credential, config, object_key, mime=None):
    client, _region = _client(credential, config)
    url = client.get_presigned_url(
        Method='PUT',
        Bucket=config['bucket'],
        Key=object_key,
        Expired=UPLOAD_PRESIGN_EXPIRES,
    )
    return url


def ensure_browser_cors(credential, config, allowed_origins=None):
    client, _region = _client(credential, config)
    origins = allowed_origins or ['*']
    if isinstance(origins, str):
        origins = [origins]
    client.put_bucket_cors(
        Bucket=config['bucket'],
        CORSConfiguration={
            'CORSRule': [{
                'AllowedOrigin': origins,
                'AllowedMethod': ['GET', 'PUT', 'POST', 'HEAD', 'DELETE'],
                'AllowedHeader': ['*'],
                'ExposeHeader': ['ETag', 'Content-Length', 'x-cos-request-id'],
                'MaxAgeSeconds': '3600',
            }],
        },
    )


def init_multipart(credential, config, object_key, file_size, mime=None):
    client, _region = _client(credential, config)
    headers = {}
    if mime:
        headers['Content-Type'] = mime
    response = client.create_multipart_upload(
        Bucket=config['bucket'],
        Key=object_key,
        **({'ContentType': mime} if mime else {}),
    )
    upload_id = response['UploadId']
    total_parts = max(1, math.ceil(file_size / UPLOAD_PART_SIZE))
    parts = presign_parts(credential, config, object_key, upload_id, 1, min(total_parts, 20))
    return upload_id, parts, total_parts


def presign_parts(credential, config, object_key, upload_id, start_part, end_part):
    client, _region = _client(credential, config)
    parts = []
    for part_number in range(start_part, end_part + 1):
        url = client.get_presigned_url(
            Method='PUT',
            Bucket=config['bucket'],
            Key=object_key,
            Params={'UploadId': upload_id, 'PartNumber': str(part_number)},
            Expired=UPLOAD_PRESIGN_EXPIRES,
        )
        parts.append({'part_number': part_number, 'url': url})
    return parts


def list_uploaded_parts(credential, config, object_key, upload_id):
    client, _region = _client(credential, config)
    parts = []
    marker = 0
    while True:
        response = client.list_parts(
            Bucket=config['bucket'],
            Key=object_key,
            UploadId=upload_id,
            PartNumberMarker=str(marker),
        )
        for part in response.get('Part', []) or []:
            parts.append({
                'part_number': int(part['PartNumber']),
                'etag': part['ETag'].strip('"') if part.get('ETag') else '',
            })
        if response.get('IsTruncated') in ('true', True):
            marker = response.get('NextPartNumberMarker', marker)
        else:
            break
    return sorted(parts, key=lambda item: item['part_number'])


def complete_multipart(credential, config, object_key, upload_id, parts):
    client, _region = _client(credential, config)
    part_tags = {
        'Part': [
            {'PartNumber': p['part_number'], 'ETag': p['etag']}
            for p in sorted(parts, key=lambda item: item['part_number'])
        ]
    }
    response = client.complete_multipart_upload(
        Bucket=config['bucket'],
        Key=object_key,
        UploadId=upload_id,
        MultipartUpload=part_tags,
    )
    return response.get('ETag', '').strip('"')


def presign_get(credential, config, object_key):
    client, _region = _client(credential, config)
    return client.get_presigned_url(
        Method='GET',
        Bucket=config['bucket'],
        Key=object_key,
        Expired=UPLOAD_PRESIGN_EXPIRES,
    )


def list_objects(credential, config, prefix='', delimiter='/', max_keys=500):
    client, _region = _client(credential, config)
    response = client.list_objects(
        Bucket=config['bucket'],
        Prefix=prefix,
        Delimiter=delimiter,
        MaxKeys=max_keys,
    )
    folders = []
    files = []
    for folder in response.get('CommonPrefixes') or []:
        folder_prefix = folder.get('Prefix', '')
        name = folder_prefix[len(prefix):].rstrip('/')
        if name:
            folders.append({'prefix': folder_prefix, 'name': name})
    for obj in response.get('Contents') or []:
        key = obj.get('Key', '')
        if key == prefix or key.endswith('/'):
            continue
        name = key[len(prefix):] if key.startswith(prefix) else key
        if not name or '/' in name.rstrip('/'):
            continue
        files.append({
            'key': key,
            'name': name,
            'size': int(obj.get('Size') or 0),
            'last_modified': obj.get('LastModified'),
        })
    return {'prefix': prefix, 'folders': folders, 'files': files}


def delete_objects(credential, config, object_keys):
    client, _region = _client(credential, config)
    if not object_keys:
        return 0
    objects = [{'Key': key} for key in object_keys]
    client.delete_objects(Bucket=config['bucket'], Delete={'Object': objects, 'Quiet': 'true'})
    return len(object_keys)


def delete_prefix(credential, config, prefix):
    client, _region = _client(credential, config)
    deleted = 0
    marker = ''
    while True:
        response = client.list_objects(
            Bucket=config['bucket'],
            Prefix=prefix,
            MaxKeys=1000,
            Marker=marker or None,
        )
        contents = response.get('Contents') or []
        if not contents:
            break
        keys = [{'Key': item['Key']} for item in contents]
        client.delete_objects(Bucket=config['bucket'], Delete={'Object': keys, 'Quiet': 'true'})
        deleted += len(keys)
        if response.get('IsTruncated'):
            marker = response.get('NextMarker') or contents[-1]['Key']
        else:
            break
    return deleted


def verify_object(credential, config, object_key, expected_size):
    client, _region = _client(credential, config)
    try:
        response = client.head_object(Bucket=config['bucket'], Key=object_key)
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}
    actual_size = int(response.get('Content-Length', 0))
    if expected_size is not None and actual_size != expected_size:
        return {'ok': False, 'error': f'大小不一致: 期望 {expected_size}, 实际 {actual_size}'}
    etag = response.get('ETag', '').strip('"')
    return {'ok': True, 'size': actual_size, 'etag': etag}
