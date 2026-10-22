import math

from cdnmanager.common import UPLOAD_MULTIPART_THRESHOLD, UPLOAD_PART_SIZE
import cdnmanager.providers.storage.storage_cos as storage_cos
import cdnmanager.providers.storage.storage_ftp as storage_ftp
import cdnmanager.providers.storage.storage_oos as storage_oos
import cdnmanager.providers.storage.storage_oss as storage_oss


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


def is_ftp_family(provider):
    return (provider or '') in {'ftp', 'sftp', 'ftps'}


def get_adapter(provider):
    if provider == 'oss':
        return storage_oss
    if provider == 'cos':
        return storage_cos
    if provider == 'oos':
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


def normalize_object_listing(listing):
    """Deduplicate folders/files from paginated or mixed delimiter listings."""
    listing = listing or {}
    folder_by_prefix = {}
    folder_by_name = {}
    for folder in listing.get('folders') or []:
        prefix = (folder.get('prefix') or '').replace('\\', '/').strip()
        if not prefix:
            continue
        if not prefix.endswith('/'):
            prefix = f'{prefix}/'
        name = (folder.get('name') or '').strip() or prefix.rstrip('/').split('/')[-1]
        if '/' in name:
            name = name.split('/', 1)[0]
        if not name:
            continue
        item = {'prefix': prefix, 'name': name}
        folder_by_prefix[prefix] = item
        # 同一层级同名目录只保留一条，避免翻页/目录占位对象造成重复节点。
        name_key = name.lower()
        if name_key not in folder_by_name:
            folder_by_name[name_key] = item

    file_by_key = {}
    for file_item in listing.get('files') or []:
        key = (file_item.get('key') or '').replace('\\', '/').strip()
        if not key or key.endswith('/'):
            continue
        name = (file_item.get('name') or '').strip() or key.rsplit('/', 1)[-1]
        if '/' in name:
            continue
        file_by_key[key] = {
            **file_item,
            'key': key,
            'name': name,
        }

    folders = sorted(folder_by_name.values(), key=lambda item: item['name'].lower())
    files = sorted(file_by_key.values(), key=lambda item: (item.get('name') or '').lower())
    return {
        **listing,
        'folders': folders,
        'files': files,
    }
