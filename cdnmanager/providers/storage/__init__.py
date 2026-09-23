from importlib import import_module

storage_cos = import_module('cdnmanager.providers.storage.storage_cos')
storage_ftp = import_module('cdnmanager.providers.storage.storage_ftp')
storage_oos = import_module('cdnmanager.providers.storage.storage_oos')
storage_oss = import_module('cdnmanager.providers.storage.storage_oss')
storage_service = import_module('cdnmanager.providers.storage.storage_service')

__all__ = ['storage_cos', 'storage_ftp', 'storage_oos', 'storage_oss', 'storage_service']