import math

from common import UPLOAD_MULTIPART_THRESHOLD, UPLOAD_PART_SIZE
from providers import storage_cos, storage_oss


def build_object_key(target_config, remote_prefix, relative_path):
    rel = relative_path.replace('\\', '/').lstrip('/')
    base = (target_config.get('base_path') or '').strip('/')
    prefix = (remote_prefix or '').replace('\\', '/').strip('/')
    segments = [part for part in [base, prefix] if part]
    head = '/'.join(segments)
    if head:
        return f'{head}/{rel}'
    return rel


def part_size_for(file_size, part_number, total_parts):
    if part_number < total_parts:
        return UPLOAD_PART_SIZE
    remaining = file_size - UPLOAD_PART_SIZE * (total_parts - 1)
    return max(remaining, 0)


def total_parts_for(file_size):
    return max(1, math.ceil(file_size / UPLOAD_PART_SIZE))


def uses_multipart(file_size):
    return file_size > UPLOAD_MULTIPART_THRESHOLD


def get_adapter(provider):
    if provider == 'oss':
        return storage_oss
    if provider == 'cos':
        return storage_cos
    raise ValueError(f'不支持的存储类型: {provider}')


def build_public_url(target_config, storage_key):
    base = (target_config.get('public_base_url') or '').strip()
    if not base:
        return None
    return base.rstrip('/') + '/' + storage_key.lstrip('/')
