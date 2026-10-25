"""Install stand-ins for cloud SDKs so unit tests can import service modules."""

import sys
import types


def _module(name):
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    return module


def install():
    if getattr(install, 'done', False):
        return
    install.done = True
    names = [
        'oss2',
        'qcloud_cos',
        'boto3',
        'botocore',
        'botocore.client',
        'botocore.exceptions',
        'requests',
        'akamai',
        'akamai.edgegrid',
        'alibabacloud_cdn20180510',
        'alibabacloud_cdn20180510.client',
        'alibabacloud_cdn20180510.models',
        'alibabacloud_tea_openapi',
        'alibabacloud_tea_openapi.models',
        'Tea',
        'Tea.core',
    ]
    for name in names:
        _module(name)
    for package in (
        'botocore',
        'akamai',
        'alibabacloud_cdn20180510',
        'alibabacloud_tea_openapi',
        'Tea',
    ):
        _module(package).__path__ = []
    _module('qcloud_cos').CosConfig = object
    _module('qcloud_cos').CosS3Client = object
    _module('botocore.client').Config = object
    _module('botocore.exceptions').ClientError = type('ClientError', (Exception,), {})
    _module('akamai.edgegrid').EdgeGridAuth = object
    _module('alibabacloud_cdn20180510.client').Client = object
    _module('alibabacloud_cdn20180510').models = _module('alibabacloud_cdn20180510.models')
    _module('alibabacloud_cdn20180510').client = _module('alibabacloud_cdn20180510.client')
    _module('alibabacloud_tea_openapi').models = _module('alibabacloud_tea_openapi.models')
    _module('Tea.core').TeaCore = object
