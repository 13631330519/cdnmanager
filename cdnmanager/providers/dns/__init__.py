"""Public dns API.

This package intentionally exposes only the interfaces currently used by other
modules. Internal helpers and connection primitives stay in their dedicated
modules and are not exported here.
"""
from cdnmanager.providers.dns.dns_service import list_dns_records, update_dns_record, create_dns_record, delete_dns_record

__all__ = [
    'list_dns_records',
    'update_dns_record', 
    'create_dns_record', 
    'delete_dns_record',
    'sync_cdn_cname',
]