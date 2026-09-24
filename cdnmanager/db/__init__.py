"""Public db API.

This package intentionally exposes only the interfaces currently used by other
modules. Internal helpers and connection primitives stay in their dedicated
modules and are not exported here.
"""

from cdnmanager.db.credentials import (
    delete_credential,
    delete_dns_credential,
    delete_root_domain,
    delete_storage_credential,
    delete_storage_target,
    get_credential,
    get_dns_credential,
    get_root_domain,
    get_storage_credential,
    get_storage_target,
    load_credentials,
    load_dns_credentials,
    load_root_domains,
    load_storage_credentials,
    load_storage_targets,
    upsert_credential,
    upsert_dns_credential,
    upsert_root_domain,
    upsert_storage_credential,
    upsert_storage_target,
)
from cdnmanager.db.domains import (
    acquire_domain_refresh,
    delete_domain_record,
    find_bound_domain,
    get_domain,
    get_url_by_id,
    get_visible_domains,
    insert_url_record,
    load_domains,
    load_refreshing_domains,
    load_refreshing_urls,
    load_url_records,
    prune_urls_for_domain,
    update_domain_fields,
    update_url_by_id,
    upsert_domain,
    user_can_access_domain,
)
from cdnmanager.db.models import ensure_database
from cdnmanager.db.projects import (
    _normalize_allowed_users,
    delete_environment,
    delete_project,
    filter_projects_tree,
    generate_api_key,
    get_environment,
    get_environment_by_name,
    get_project,
    get_project_by_name,
    get_user_project_ids,
    list_storage_targets_for_environment,
    load_environments,
    load_projects,
    load_projects_tree,
    remove_user_from_projects,
    resolve_storage_target_for_domain,
    sync_domain_tags_from_ids,
    sync_user_project_authorization,
    upsert_environment,
    upsert_project,
    user_can_access_project,
)
from cdnmanager.db.uploads import (
    cleanup_finished_upload_job,
    count_upload_files,
    count_upload_jobs,
    delete_upload_job_cascade,
    get_upload_file,
    get_upload_job,
    increment_upload_job_totals,
    insert_upload_files,
    insert_upload_job,
    insert_upload_parts,
    list_failed_upload_files,
    list_stale_uploading_files,
    list_upload_files,
    list_upload_jobs,
    list_upload_parts,
    recalculate_upload_job_stats,
    update_upload_file,
    update_upload_job,
    update_upload_part,
)
from cdnmanager.db.users import (
    delete_user,
    get_user,
    load_users,
    remove_user_from_domains,
    upsert_user,
)
from cdnmanager.db.connection import (
    try_acquire_polling_lease,
)
__all__ = [
    #models
    'ensure_database','try_acquire_polling_lease',
    #users
    'delete_user', 'get_user','load_users', 'remove_user_from_domains', 'upsert_user',
    #credentials
    'delete_credential', 'get_credential','load_credentials', 'upsert_credential', 
    'delete_dns_credential', 'get_dns_credential', 'load_dns_credentials', 'upsert_dns_credential', 
    'delete_storage_credential', 'get_storage_credential', 'load_storage_credentials', 'upsert_storage_credential',
    'delete_storage_target', 'get_storage_target', 'load_storage_targets', 'upsert_storage_target',
    #domains
    'acquire_domain_refresh', 'delete_domain_record', 'find_bound_domain', 'get_domain',
    'get_url_by_id','get_visible_domains', 'insert_url_record', 'load_domains',
    'load_url_records', 'load_refreshing_domains','load_refreshing_urls',
    'prune_urls_for_domain', 'upsert_domain',  'update_domain_fields',
    'update_url_by_id', 'user_can_access_domain',
    'delete_root_domain','get_root_domain','load_root_domains',  'upsert_root_domain', 
    #projects
    'generate_api_key', '_normalize_allowed_users', 'user_can_access_project', 'resolve_storage_target_for_domain',
    'load_projects', 'get_project', 'get_project_by_name', 'upsert_project', 'delete_project',
    'load_environments', 'get_environment', 'get_environment_by_name', 'upsert_environment', 'delete_environment',
    'list_storage_targets_for_environment', 'load_projects_tree', 'filter_projects_tree', 'remove_user_from_projects',
    'get_user_project_ids','sync_domain_tags_from_ids','sync_user_project_authorization',
    #uploads
    'list_upload_jobs', 'list_upload_files', 'get_upload_job', 'get_upload_file', 'insert_upload_job',
    'insert_upload_files', 'update_upload_file', 'update_upload_job', 'increment_upload_job_totals',
    'count_upload_jobs', 'count_upload_files', 'list_failed_upload_files', 'list_stale_uploading_files',
    'insert_upload_parts', 'list_upload_parts', 'update_upload_part', 'recalculate_upload_job_stats',
    'delete_upload_job_cascade', 'cleanup_finished_upload_job', 
]
