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
    headers = {}
    if mime:
        headers['Content-Type'] = mime
    url = client.get_presigned_url(
        Method='PUT',
        Bucket=config['bucket'],
        Key=object_key,
        Expired=UPLOAD_PRESIGN_EXPIRES,
        Headers=headers or None,
    )
    return url


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
