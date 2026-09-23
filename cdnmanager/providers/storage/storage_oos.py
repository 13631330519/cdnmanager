"""天翼云 OOS — S3 兼容 API（boto3）。"""

import math

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from cdnmanager.common import UPLOAD_PART_SIZE, UPLOAD_PRESIGN_EXPIRES
from cdnmanager.providers.storage.cors_merge import merge_s3_rules


def _endpoint(config):
    endpoint = (config.get('endpoint') or '').strip()
    if not endpoint:
        region = (config.get('region') or '').strip()
        if region:
            endpoint = f'https://{region}.oos-cn.ctyunapi.cn'
        else:
            endpoint = 'https://oos-cn.ctyunapi.cn'
    if not endpoint.startswith('http'):
        endpoint = f'https://{endpoint}'
    return endpoint.rstrip('/')


def _client(credential, config):
    return boto3.client(
        's3',
        endpoint_url=_endpoint(config),
        aws_access_key_id=credential['access_key'],
        aws_secret_access_key=credential['secret_key'],
        region_name=(config.get('region') or 'cn').strip() or 'cn',
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
    )


def _bucket(config):
    return config['bucket']


def presign_put(credential, config, object_key, mime=None):
    client = _client(credential, config)
    params = {'Bucket': _bucket(config), 'Key': object_key}
    if mime:
        params['ContentType'] = mime
    return client.generate_presigned_url(
        'put_object',
        Params=params,
        ExpiresIn=UPLOAD_PRESIGN_EXPIRES,
    )


def _load_existing_s3_cors_rules(client, bucket):
    try:
        response = client.get_bucket_cors(Bucket=bucket)
        return list(response.get('CORSRules') or [])
    except ClientError as exc:
        code = exc.response.get('Error', {}).get('Code', '')
        if code in {'NoSuchCORSConfiguration', 'NoSuchBucketCors'}:
            return []
        raise


def ensure_browser_cors(credential, config, allowed_origins=None):
    client = _client(credential, config)
    bucket = _bucket(config)
    origins = allowed_origins or ['*']
    existing_rules = _load_existing_s3_cors_rules(client, bucket)
    merged_rules = merge_s3_rules(existing_rules, origins)
    client.put_bucket_cors(
        Bucket=bucket,
        CORSConfiguration={'CORSRules': merged_rules},
    )


def init_multipart(credential, config, object_key, file_size, mime=None):
    client = _client(credential, config)
    params = {'Bucket': _bucket(config), 'Key': object_key}
    if mime:
        params['ContentType'] = mime
    upload_id = client.create_multipart_upload(**params)['UploadId']
    total_parts = max(1, math.ceil(file_size / UPLOAD_PART_SIZE))
    parts = presign_parts(credential, config, object_key, upload_id, 1, min(total_parts, 20))
    return upload_id, parts, total_parts


def presign_parts(credential, config, object_key, upload_id, start_part, end_part):
    client = _client(credential, config)
    parts = []
    for part_number in range(start_part, end_part + 1):
        url = client.generate_presigned_url(
            'upload_part',
            Params={
                'Bucket': _bucket(config),
                'Key': object_key,
                'UploadId': upload_id,
                'PartNumber': part_number,
            },
            ExpiresIn=UPLOAD_PRESIGN_EXPIRES,
        )
        parts.append({'part_number': part_number, 'url': url})
    return parts


def list_uploaded_parts(credential, config, object_key, upload_id):
    client = _client(credential, config)
    parts = []
    marker = 0
    while True:
        resp = client.list_parts(
            Bucket=_bucket(config),
            Key=object_key,
            UploadId=upload_id,
            PartNumberMarker=marker,
        )
        for part in resp.get('Parts') or []:
            parts.append({
                'part_number': part['PartNumber'],
                'etag': part['ETag'].strip('"') if part.get('ETag') else part.get('ETag'),
            })
        if not resp.get('IsTruncated'):
            break
        marker = resp['NextPartNumberMarker']
    return sorted(parts, key=lambda item: item['part_number'])


def complete_multipart(credential, config, object_key, upload_id, parts):
    client = _client(credential, config)
    tags = sorted(
        [{'PartNumber': p['part_number'], 'ETag': p['etag']} for p in parts],
        key=lambda item: item['PartNumber'],
    )
    resp = client.complete_multipart_upload(
        Bucket=_bucket(config),
        Key=object_key,
        UploadId=upload_id,
        MultipartUpload={'Parts': tags},
    )
    etag = resp.get('ETag')
    return etag.strip('"') if etag else etag


def delete_objects(credential, config, object_keys):
    client = _client(credential, config)
    bucket = _bucket(config)
    for i in range(0, len(object_keys), 1000):
        batch = object_keys[i:i + 1000]
        client.delete_objects(
            Bucket=bucket,
            Delete={'Objects': [{'Key': key} for key in batch], 'Quiet': True},
        )
    return len(object_keys)


def delete_prefix(credential, config, prefix):
    client = _client(credential, config)
    bucket = _bucket(config)
    deleted = 0
    token = None
    while True:
        kwargs = {'Bucket': bucket, 'Prefix': prefix}
        if token:
            kwargs['ContinuationToken'] = token
        resp = client.list_objects_v2(**kwargs)
        contents = resp.get('Contents') or []
        if contents:
            client.delete_objects(
                Bucket=bucket,
                Delete={'Objects': [{'Key': obj['Key']} for obj in contents], 'Quiet': True},
            )
            deleted += len(contents)
        if not resp.get('IsTruncated'):
            break
        token = resp.get('NextContinuationToken')
    return deleted


def presign_get(credential, config, object_key):
    client = _client(credential, config)
    return client.generate_presigned_url(
        'get_object',
        Params={'Bucket': _bucket(config), 'Key': object_key},
        ExpiresIn=UPLOAD_PRESIGN_EXPIRES,
    )


def list_objects(credential, config, prefix='', delimiter='/', max_keys=500):
    client = _client(credential, config)
    resp = client.list_objects_v2(
        Bucket=_bucket(config),
        Prefix=prefix,
        Delimiter=delimiter,
        MaxKeys=max_keys,
    )
    folders = []
    for folder in resp.get('CommonPrefixes') or []:
        p = folder.get('Prefix') or ''
        name = p[len(prefix):].rstrip('/')
        if name:
            folders.append({'prefix': p, 'name': name})
    files = []
    for obj in resp.get('Contents') or []:
        key = obj.get('Key') or ''
        if key == prefix or key.endswith('/'):
            continue
        name = key[len(prefix):] if key.startswith(prefix) else key
        if not name or '/' in name.rstrip('/'):
            continue
        files.append({
            'key': key,
            'name': name,
            'size': obj.get('Size') or 0,
            'last_modified': obj.get('LastModified'),
        })
    return {'prefix': prefix, 'folders': folders, 'files': files}


def verify_object(credential, config, object_key, expected_size):
    client = _client(credential, config)
    try:
        meta = client.head_object(Bucket=_bucket(config), Key=object_key)
    except ClientError as exc:
        code = exc.response.get('Error', {}).get('Code', '')
        if code in ('404', 'NoSuchKey', 'NotFound'):
            return {'ok': False, 'error': '对象不存在'}
        return {'ok': False, 'error': str(exc)}
    actual_size = meta.get('ContentLength')
    if expected_size is not None and actual_size != expected_size:
        return {'ok': False, 'error': f'大小不一致: 期望 {expected_size}, 实际 {actual_size}'}
    etag = meta.get('ETag', '').strip('"') if meta.get('ETag') else None
    return {'ok': True, 'size': actual_size, 'etag': etag}
