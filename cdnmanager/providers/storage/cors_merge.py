"""Merge CDN Manager browser-upload CORS rules without replacing existing bucket rules."""

UPLOAD_METHODS = frozenset({'GET', 'PUT', 'POST', 'HEAD', 'DELETE'})


def normalize_origins(origins):
    if origins is None:
        return {'*'}
    if isinstance(origins, str):
        origins = [origins]
    return set(origins) or {'*'}


def origins_covered(rule_origins, needed_origins):
    rule_set = normalize_origins(rule_origins)
    need_set = normalize_origins(needed_origins)
    if '*' in rule_set:
        return True
    return need_set.issubset(rule_set)


def methods_cover_upload(rule_methods):
    methods = {str(method).upper() for method in (rule_methods or [])}
    return UPLOAD_METHODS.issubset(methods)


def headers_allow_all(rule_headers):
    headers = rule_headers or []
    if isinstance(headers, str):
        headers = [headers]
    return '*' in headers


def rule_satisfies_upload(rule_origins, rule_methods, rule_headers, needed_origins):
    return (
        origins_covered(rule_origins, needed_origins)
        and methods_cover_upload(rule_methods)
        and headers_allow_all(rule_headers)
    )


def build_cos_upload_rule(origins):
    return {
        'AllowedOrigin': sorted(normalize_origins(origins)),
        'AllowedMethod': sorted(UPLOAD_METHODS),
        'AllowedHeader': ['*'],
        'ExposeHeader': ['ETag', 'Content-Length', 'x-cos-request-id'],
        'MaxAgeSeconds': '3600',
    }


def merge_cos_rules(existing_rules, origins):
    rules = list(existing_rules or [])
    if any(
        rule_satisfies_upload(
            rule.get('AllowedOrigin'),
            rule.get('AllowedMethod'),
            rule.get('AllowedHeader'),
            origins,
        )
        for rule in rules
    ):
        return rules
    return rules + [build_cos_upload_rule(origins)]


def build_s3_upload_rule(origins):
    return {
        'AllowedOrigins': sorted(normalize_origins(origins)),
        'AllowedMethods': sorted(UPLOAD_METHODS),
        'AllowedHeaders': ['*'],
        'ExposeHeaders': ['ETag', 'Content-Length'],
        'MaxAgeSeconds': 3600,
    }


def merge_s3_rules(existing_rules, origins):
    rules = list(existing_rules or [])
    if any(
        rule_satisfies_upload(
            rule.get('AllowedOrigins'),
            rule.get('AllowedMethods'),
            rule.get('AllowedHeaders'),
            origins,
        )
        for rule in rules
    ):
        return rules
    return rules + [build_s3_upload_rule(origins)]
