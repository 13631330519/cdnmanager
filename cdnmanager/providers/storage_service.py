import math

from cdnmanager.common import UPLOAD_MULTIPART_THRESHOLD, UPLOAD_PART_SIZE
from cdnmanager.providers import storage_cos, storage_ftp, storage_oss


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
    if provider == 'oos':
        from cdnmanager.providers import storage_oos
        return storage_oos
    if provider in {'ftp', 'sftp', 'ftps'}:
        return storage_ftp
    raise ValueError(f'不支持的存储类型: {provider}')


def ensure_browser_cors(adapter, credential, config, allowed_origins=None):
    if not hasattr(adapter, 'ensure_browser_cors'):
        return
    adapter.ensure_browser_cors(credential, config, allowed_origins)


def build_list_prefix(target_config, remote_prefix=''):
    base = (target_config.get('base_path') or '').strip('/')
    extra = (remote_prefix or '').replace('\\', '/').strip('/')
    segments = [part for part in [base, extra] if part]
    if not segments:
        return ''
    return '/'.join(segments) + '/'


def build_public_url(target_config, storage_key):
    base = (target_config.get('public_base_url') or '').strip()
    if not base:
        return None
    return base.rstrip('/') + '/' + storage_key.lstrip('/')
