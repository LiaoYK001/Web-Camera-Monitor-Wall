#!/usr/bin/env python3
"""Shared agent task ledger and reproducible Markdown views (stdlib only)."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STATUSES = ('planned', 'in_progress', 'blocked', 'done', 'on_hold')
LABELS = dict(zip(STATUSES, ('待开始', '进行中', '阻塞', '完成', '暂停')))


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        mode = None
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        stream.write(content)
        name = stream.name
    try:
        # mkstemp starts at 0600. Restore the existing mode so a replacement
        # does not mask the directory's inherited collaborative ACL entries.
        # Brand-new files retain the private default until explicitly shared.
        if mode is not None:
            os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(folder):
    # One stable file, never unlinked: all processes lock the same inode/byte.
    with (folder / '.sync.lock').open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def overlaps(left, right):
    return any(a == b or a in b.parents or b in a.parents
               for a in map(PurePosixPath, left) for b in map(PurePosixPath, right))


def validate(state):
    tasks = state['tasks']
    ids = [task['id'] for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError('重复 task ID')
    if state['revision'] != len(state['events']) or [e['sequence'] for e in state['events']] != list(range(1, state['revision'] + 1)):
        raise ValueError('日志顺序/快照版本不一致；合并账本时必须保留所有事件并统一编号')
    by_id = {task['id']: task for task in tasks}
    milestones = {m['id'] for m in state['milestones']}
    for task in tasks:
        if task['status'] not in STATUSES or task['milestone'] not in milestones:
            raise ValueError(f"{task['id']}: 无效状态/里程碑")
        if any(dep not in by_id for dep in task['depends_on']):
            raise ValueError(f"{task['id']}: 未知依赖")
        for path in task['scope']:
            part = PurePosixPath(path)
            if not path or part.is_absolute() or '..' in part.parts or '\\' in path or ':' in path:
                raise ValueError(f"{task['id']}: scope 必须是仓库相对路径")
        if task['status'] == 'in_progress' and not task['owner']:
            raise ValueError(f"{task['id']}: 进行中任务必须有 owner")
        if task['status'] == 'blocked' and not task['blocker']:
            raise ValueError(f"{task['id']}: 阻塞必须写明原因")
        if task['status'] in ('in_progress', 'done'):
            if any(by_id[dep]['status'] != 'done' for dep in task['depends_on']):
                raise ValueError(f"{task['id']}: 依赖未完成")
        if task['status'] == 'done' and not task['evidence']:
            raise ValueError(f"{task['id']}: 完成必须有证据")
    visited, active = set(), set()

    def visit(task_id):
        if task_id in active:
            raise ValueError('任务依赖成环')
        if task_id in visited:
            return
        active.add(task_id)
        for dep in by_id[task_id]['depends_on']:
            visit(dep)
        active.remove(task_id)
        visited.add(task_id)

    for task_id in ids:
        visit(task_id)
    claimed = [task for task in tasks if task['owner'] and task['status'] == 'in_progress']
    for index, left in enumerate(claimed):
        for right in claimed[index + 1:]:
            if overlaps(left['scope'], right['scope']):
                raise ValueError(f"文件范围冲突: {left['id']} / {right['id']}")


def cell(text):
    return str(text or '—').replace('|', '\\|').replace('\n', ' ')


def render(state):
    tasks = state['tasks']
    head = (f"> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。\n"
            f"> 快照版本 {state['revision']} · {state['updated_at']}（UTC+08）\n\n")
    links = '[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)\n\n'
    status = '# 当前进度 / Current status\n\n' + head + links
    status += f"{state['summary']}\n\n基线源码：`{state['baseline_revision']}`。本页是仓库证据快照，不是实时 CI/Release 查询。\n\n"
    status += '## 基线事实与边界\n\n以下为建账时核对的事实；后续进展以任务和日志中的新证据为准。\n\n' + ''.join(f'- {line}\n' for line in state['facts'])
    status += '\n## 阶段计数\n\n| 阶段 | 已关闭/登记任务 | 当前状态 |\n| --- | --- | --- |\n'
    roadmap = '# 详细执行路线图 / Execution roadmap\n\n' + head + links
    roadmap += '沿用已有 R0–R7 目标，并单列用户已选择的 v4.5 预览交付。下列计数只表示登记任务关闭情况，不是产品完成百分比，也不替代原始验收门槛。\n\n'
    for milestone in state['milestones']:
        group = [task for task in tasks if task['milestone'] == milestone['id']]
        done = sum(task['status'] == 'done' for task in group)
        phase = '完成' if group and done == len(group) else ('暂停' if group and all(t['status'] == 'on_hold' for t in group) else '未关闭')
        status += f"| {cell(milestone['id'] + ' ' + milestone['title'])} | {done}/{len(group)} | {phase} |\n"
        roadmap += f"## {milestone['id']} · {milestone['title']}\n\n{milestone['goal']}\n\n完成条件：{milestone['exit_criteria']}\n\n"
        for task in group:
            roadmap += f"- **{task['id']} · {LABELS[task['status']]}**：{task['title']}；依赖：{', '.join(task['depends_on']) or '无'}。验收：{'；'.join(task['acceptance'])}\n"
        roadmap += '\n'
    status += '\n## 接下来可认领\n\n'
    by_id = {task['id']: task for task in tasks}
    ready = [task for task in tasks if task['status'] == 'planned' and all(by_id[d]['status'] == 'done' for d in task['depends_on'])]
    for task in ready:
        status += f"- `{task['id']}` {task['priority']} · {task['title']}。下一步：{task['next_step']}\n"
    status += '\n原始依据：[完整任务书](../windows-webobs-wall-release-plan-2026-11-11.md)、[功能矩阵](../windows-native-feature-parity.md)、[逐轮执行记录](../windows-obs-parity-execution.md)、[v4.5 范围](../release-notes-v4.5.md)。\n'
    board = '# 任务与认领 / Tasks and ownership\n\n' + head + links
    board += '| ID | 优先级 | 状态 | 负责人 | 任务 | 依赖 |\n| --- | --- | --- | --- | --- | --- |\n'
    for task in tasks:
        board += '| ' + ' | '.join(map(cell, [task['id'], task['priority'], LABELS[task['status']], task['owner'], task['title'], ', '.join(task['depends_on'])])) + ' |\n'
    for task in tasks:
        board += f"\n## {task['id']} · {task['title']}\n\n- 修改范围：{', '.join('`' + path + '`' for path in task['scope'])}\n- 验收：{'；'.join(task['acceptance'])}\n- 下一步：{task['next_step']}\n- 阻塞：{task['blocker'] or '无'}\n- 证据：{'；'.join(task['evidence']) or '尚未提供'}\n- 最新记录：{task.get('last_note') or '待认领'}\n- 最近更新：{task['updated_at']}\n"
    log = '# 开发日志 / Development log\n\n' + head + links
    log += '既有产品开发历史继续保留在 [原始执行记录](../windows-obs-parity-execution.md)，不把本轮文档工作当作产品验证。\n\n'
    for event in reversed(state['events']):
        log += f"## #{event['sequence']} · {event['at']} · {event['action']}\n\n- Agent：`{event['agent']}`；任务：`{event.get('task') or '全局'}`\n- 记录：{event['note']}\n- 证据：{'；'.join(event.get('evidence', [])) or '无新增验收证据'}\n- 源码：`{event['git_revision']}`\n"
    handoff = '# 当前交接 / Current handoff\n\n' + head + links
    handoff += '新 Agent 先检查 `git status --short --branch`，阅读根目录 AGENTS.md 和 PLAYBOOK.md；认领后才改动任务范围。其他 Agent 的未提交修改不能删除、重置或覆盖。\n\n'
    handoff += '## 进行中、阻塞与已暂停\n\n'
    for task in tasks:
        if task['status'] in ('in_progress', 'blocked', 'on_hold'):
            handoff += f"- **{task['id']} · {LABELS[task['status']]}**；负责人：{task['owner'] or '未认领'}；阻塞：{task['blocker'] or '无'}；下一步：{task['next_step']}\n"
    handoff += '\n## 最近一次同步\n\n' + state['events'][-1]['note'] + '\n\n以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。\n'
    return {'STATUS.md': status, 'ROADMAP.md': roadmap, 'TASKS.md': board, 'DEVLOG.md': log, 'HANDOFF.md': handoff}


def git_revision(root):
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else 'unversioned'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Checkout root; defaults to this script’s checkout')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('status', 'render', 'check'):
        commands.add_parser(name)
    add = commands.add_parser('add', help='Register a newly agreed task; never expands release authorization')
    add.add_argument('task')
    add.add_argument('--agent', required=True)
    add.add_argument('--note', required=True)
    add.add_argument('--title', required=True)
    add.add_argument('--milestone', required=True)
    add.add_argument('--priority', choices=('P0', 'P1', 'P2'), default='P1')
    add.add_argument('--scope', action='append', required=True)
    add.add_argument('--acceptance', action='append', required=True)
    add.add_argument('--depends-on', action='append', default=[])
    add.add_argument('--next', dest='next_step', required=True)
    add.add_argument('--evidence', action='append', default=[])
    for name in ('claim', 'update', 'release', 'log'):
        command = commands.add_parser(name)
        command.add_argument('task')
        command.add_argument('--agent', required=True, help='Unique client/session identifier, not just a model name')
        command.add_argument('--note', required=True)
        command.add_argument('--evidence', action='append', default=[])
        if name == 'update':
            command.add_argument('--status', choices=STATUSES)
            command.add_argument('--next', dest='next_step')
            command.add_argument('--blocker')
            command.add_argument('--scope', action='append', help='Replace scope after coordination; repeat for all owned paths')
    args = parser.parse_args()
    root = args.root.resolve()
    folder = root / 'docs/coordination'
    with locked(folder):
        path = folder / 'state.json'
        state = json.loads(path.read_text(encoding='utf-8'))
        validate(state)
        if args.command == 'status':
            print(render(state)['STATUS.md'])
            return
        if args.command not in ('check', 'render'):
            task = next((task for task in state['tasks'] if task['id'] == args.task), None)
            if args.command == 'add':
                if task or not re.fullmatch(r'[A-Z][A-Z0-9]*-[0-9]{3}', args.task):
                    raise ValueError('task ID 已存在或格式不符，例如 R2-005')
                task = dict(id=args.task, milestone=args.milestone, title=args.title,
                            priority=args.priority, status='planned', owner=None,
                            scope=args.scope, depends_on=args.depends_on,
                            acceptance=args.acceptance, evidence=[], blocker='',
                            next_step=args.next_step, updated_at=now(), last_note='')
                state['tasks'].append(task)
            elif task is None:
                raise ValueError(f'未知任务: {args.task}')
            if not args.agent.strip() or not args.note.strip():
                raise ValueError('agent/note 不能为空')
            if task['owner'] and task['owner'] != args.agent:
                raise ValueError(f"{task['id']} 已由 {task['owner']} 认领；请先协调交接")
            if args.command == 'add':
                pass
            elif args.command == 'claim':
                if task['status'] != 'planned':
                    raise ValueError('仅可认领 planned 任务；阻塞/暂停/已完成任务需先明确调整状态')
                by_id = {t['id']: t for t in state['tasks']}
                if any(by_id[d]['status'] != 'done' for d in task['depends_on']):
                    raise ValueError('依赖尚未完成')
                task.update(owner=args.agent, status='in_progress', blocker='')
            elif args.command == 'release':
                if task['owner'] != args.agent or task['status'] != 'in_progress':
                    raise ValueError('只能释放自己正在执行的任务；已完成/阻塞记录不能由 release 抹去')
                task.update(owner=None, status='planned')
            elif args.command == 'update':
                if args.scope:
                    if task['owner'] != args.agent or task['status'] != 'in_progress':
                        raise ValueError('调整修改范围前必须持有进行中的任务')
                    task['scope'] = args.scope
                status = args.status or task['status']
                if status in ('in_progress', 'done') and task['owner'] != args.agent:
                    raise ValueError('开始/完成前必须先认领任务')
                if task['status'] == 'on_hold' and status != 'on_hold':
                    raise ValueError('暂停范围只可在用户明确恢复后，审查修改 state.json 并记录决定')
                if status == 'done' and not args.evidence:
                    raise ValueError('完成需要本轮 --evidence；历史证据不能自动当作本轮通过')
                task['status'] = status
                if args.next_step:
                    task['next_step'] = args.next_step
                if args.blocker is not None:
                    task['blocker'] = args.blocker
                elif status != 'blocked':
                    task['blocker'] = ''
                if status in ('done', 'planned', 'on_hold'):
                    task['owner'] = None
            elif task['owner'] != args.agent:
                raise ValueError('任务日志只能由当前负责人追加；请先认领')
            stamp = now()
            task['updated_at'] = stamp
            task['last_note'] = args.note
            task['evidence'] = list(dict.fromkeys(task['evidence'] + args.evidence))
            state['revision'] += 1
            state['updated_at'] = stamp
            state['events'].append({'sequence': len(state['events']) + 1, 'at': stamp,
                                    'agent': args.agent, 'task': args.task, 'action': args.command,
                                    'note': args.note, 'evidence': args.evidence,
                                    'git_revision': git_revision(root)})
            validate(state)
            atomic_write(path, json.dumps(state, ensure_ascii=False, indent=2) + '\n')
        views = render(state)
        if args.command == 'check':
            stale = [name for name, content in views.items()
                     if not (folder / name).exists() or (folder / name).read_text(encoding='utf-8') != content]
            if stale:
                raise ValueError('视图未同步: ' + ', '.join(stale) + '; run: python scripts/agent-sync.py render')
            print(f"OK: revision {state['revision']}, {len(state['tasks'])} tasks, {len(views)} synchronized views")
        else:
            for name, content in views.items():
                atomic_write(folder / name, content)
            print(f"Synchronized revision {state['revision']}")


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        print(f'agent-sync: {error}', file=sys.stderr)
        sys.exit(1)
