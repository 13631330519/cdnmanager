#!/usr/bin/env python3
"""
从 TXT 批量创建用户并写回密码。

文件格式（Tab 分隔，每行一条）：
    用户名<TAB>项目1,项目2,...<TAB>密码

- 项目名用英文逗号分隔，支持项目名称或项目 ID。
- 密码列留空则自动生成随机密码，处理成功后写回该列。
- 以 # 开头的行与空行原样保留。

用法（在仓库根目录）：
    python scripts/batch_create_users.py users.txt
    python scripts/batch_create_users.py users.txt --dry-run
    python scripts/batch_create_users.py users.txt --update   # 已存在用户：同步项目授权
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from werkzeug.security import generate_password_hash

from cdnmanager.db.models import ensure_database, get_user, upsert_user
from cdnmanager.db.projects import (
    get_project,
    get_project_by_name,
    sync_user_project_authorization,
)


def generate_password() -> str:
    return secrets.token_urlsafe(12)


def resolve_project_ids(raw_projects: str) -> tuple[list[str], list[str]]:
    """Return (project_ids, errors)."""
    if not raw_projects or not raw_projects.strip():
        return [], []

    project_ids = []
    errors = []
    for token in raw_projects.split(','):
        name_or_id = token.strip()
        if not name_or_id:
            continue
        project = get_project_by_name(name_or_id) or get_project(name_or_id)
        if not project:
            errors.append(f'项目不存在: {name_or_id}')
            continue
        if project['id'] not in project_ids:
            project_ids.append(project['id'])
    return project_ids, errors


def parse_data_line(line: str) -> tuple[str, str, str] | None:
    stripped = line.rstrip('\n\r')
    if not stripped or stripped.lstrip().startswith('#'):
        return None
    parts = stripped.split('\t')
    if len(parts) < 2:
        raise ValueError(f'格式错误（至少需要 用户名\\t项目列表）: {stripped!r}')
    username = parts[0].strip()
    projects = parts[1].strip()
    password = parts[2].strip() if len(parts) >= 3 else ''
    if not username:
        raise ValueError(f'用户名为空: {stripped!r}')
    return username, projects, password


def format_data_line(username: str, projects: str, password: str) -> str:
    return f'{username}\t{projects}\t{password}'


def process_user(
    username: str,
    projects_raw: str,
    password: str,
    *,
    role: str,
    update_existing: bool,
    dry_run: bool,
) -> tuple[str, str | None, str | None]:
    """
    Returns (status, password_to_write_back, error_message).
    status: created | updated | skipped | failed
    """
    if username == 'admin':
        return 'failed', password or None, '不能修改 admin 用户'

    project_ids, project_errors = resolve_project_ids(projects_raw)
    if project_errors:
        return 'failed', password or None, '; '.join(project_errors)

    existing = get_user(username)
    if existing and not update_existing:
        return 'skipped', password or None, '用户已存在（加 --update 可同步项目）'

    plain_password = password
    generated = False
    if not plain_password:
        plain_password = generate_password()
        generated = True

    if dry_run:
        action = 'update' if existing else 'create'
        note = f'[dry-run] 将{action}用户 {username}，项目 {project_ids or "（无）"}'
        if generated:
            note += f'，密码 {plain_password}'
        print(note)
        return ('updated' if existing else 'created'), plain_password, None

    now = datetime.now().isoformat()
    upsert_user({
        'username': username,
        'password': generate_password_hash(plain_password),
        'role': role if not existing else existing.get('role', role),
        'created_at': existing.get('created_at') if existing else now,
        'updated_at': now,
    })
    if role != 'admin':
        sync_user_project_authorization(username, project_ids)

    if existing:
        print(f'[updated] {username} -> 项目 {project_ids or "（无）"}')
        if generated:
            print(f'          新密码: {plain_password}')
        return 'updated', plain_password, None

    print(f'[created] {username} -> 项目 {project_ids or "（无）"}')
    if generated:
        print(f'          密码: {plain_password}')
    else:
        print('          密码: （使用文件中指定值）')
    return 'created', plain_password, None


def load_lines(path: str) -> list[str]:
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read().splitlines()


def write_lines(path: str, lines: list[str]) -> None:
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(lines))
        if lines:
            fh.write('\n')


def main() -> int:
    parser = argparse.ArgumentParser(description='从 Tab 分隔 TXT 批量创建用户')
    parser.add_argument('input_file', help='用户列表 TXT 路径')
    parser.add_argument('--dry-run', action='store_true', help='仅预览，不写数据库与文件')
    parser.add_argument(
        '--update',
        action='store_true',
        help='已存在用户时同步项目授权；密码列为空则重置为随机密码',
    )
    parser.add_argument('--role', default='user', choices=['user', 'domain_admin'], help='新用户角色')
    parser.add_argument('--no-backup', action='store_true', help='写回前不备份原文件')
    args = parser.parse_args()

    input_path = os.path.abspath(args.input_file)
    if not os.path.isfile(input_path):
        print(f'文件不存在: {input_path}', file=sys.stderr)
        return 1

    ensure_database()

    raw_lines = load_lines(input_path)
    output_lines: list[str] = []
    stats = {'created': 0, 'updated': 0, 'skipped': 0, 'failed': 0}

    for line_no, line in enumerate(raw_lines, start=1):
        try:
            parsed = parse_data_line(line)
        except ValueError as exc:
            print(f'[failed] 第 {line_no} 行: {exc}', file=sys.stderr)
            stats['failed'] += 1
            output_lines.append(line)
            continue

        if parsed is None:
            output_lines.append(line)
            continue

        username, projects_raw, password = parsed
        status, password_out, error = process_user(
            username,
            projects_raw,
            password,
            role=args.role,
            update_existing=args.update,
            dry_run=args.dry_run,
        )

        if error:
            print(f'[{status}] 第 {line_no} 行 {username}: {error}', file=sys.stderr)
            stats[status if status in stats else 'failed'] += 1
            output_lines.append(line)
            continue

        stats[status if status in stats else 'failed'] += 1
        if password_out is not None:
            output_lines.append(format_data_line(username, projects_raw, password_out))
        else:
            output_lines.append(line)

    print(
        f'\n完成: 创建 {stats["created"]}, 更新 {stats["updated"]}, '
        f'跳过 {stats["skipped"]}, 失败 {stats["failed"]}'
    )

    if args.dry_run:
        print('（dry-run 模式，未写回文件）')
        return 0 if stats['failed'] == 0 else 1

    if not args.no_backup:
        backup_path = f'{input_path}.bak'
        shutil.copy2(input_path, backup_path)
        print(f'已备份: {backup_path}')

    write_lines(input_path, output_lines)
    print(f'已写回: {input_path}')
    return 0 if stats['failed'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
