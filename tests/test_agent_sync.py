"""Exercise competing agent writes and evidence/ownership boundaries in temp checkouts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/agent-sync.py'


class AgentSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'docs/coordination'
        self.folder.mkdir(parents=True)
        source = SCRIPT.parent.parent / 'docs/coordination/state.json'
        state = json.loads(source.read_text(encoding='utf-8'))
        template = state['tasks'][0]
        state['tasks'] = []
        for index in range(3):
            task = dict(template, id=f'TEST-{index:03}', milestone='COORD', status='planned',
                        owner=None, evidence=[], depends_on=[], scope=[f'component-{index}'])
            state['tasks'].append(task)
        self.write(state)
        self.run_ok('render')

    def write(self, state):
        (self.folder / 'state.json').write_text(json.dumps(state), encoding='utf-8')

    def read(self):
        return json.loads((self.folder / 'state.json').read_text(encoding='utf-8'))

    def command(self, *args):
        return [sys.executable, '-B', str(SCRIPT), '--root', str(self.root), *args]

    def run_ok(self, *args):
        result = subprocess.run(self.command(*args), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def claim(self, task, agent):
        return ('claim', task, '--agent', agent, '--note', 'isolated concurrency test')

    def test_competing_claims_have_exactly_one_owner(self):
        before = self.read()['revision']
        workers = [subprocess.Popen(self.command(*self.claim('TEST-000', agent)),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                   for agent in ('client-a', 'client-b')]
        for worker in workers:
            worker.communicate(timeout=30)
        self.assertEqual(sorted(p.returncode for p in workers), [0, 1])
        state = self.read()
        self.assertIn(state['tasks'][0]['owner'], ('client-a', 'client-b'))
        self.assertEqual(state['revision'], before + 1)
        self.run_ok('check')

    def test_disjoint_writes_preserve_both_updates(self):
        before = self.read()['revision']
        workers = [subprocess.Popen(self.command(*self.claim(f'TEST-{index:03}', f'client-{index}')),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                   for index in range(2)]
        for worker in workers:
            out, err = worker.communicate(timeout=30)
            self.assertEqual(worker.returncode, 0, err)
        state = self.read()
        self.assertEqual(state['revision'], before + 2)
        self.assertEqual([task['owner'] for task in state['tasks'][:2]], ['client-0', 'client-1'])
        self.run_ok('check')

    def test_overlapping_scopes_refuse_second_writer(self):
        state = self.read()
        state['tasks'][0]['scope'] = ['native-host']
        state['tasks'][1]['scope'] = ['native-host/src/file.cpp']
        self.write(state)
        self.run_ok(*self.claim('TEST-000', 'owner-a'))
        before = (self.folder / 'state.json').read_bytes()
        result = subprocess.run(self.command(*self.claim('TEST-001', 'owner-b')),
                                capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.folder / 'state.json').read_bytes(), before)
        self.run_ok('check')

    def test_dependencies_current_evidence_and_stale_views(self):
        state = self.read()
        state['tasks'][1]['depends_on'] = ['TEST-000']
        self.write(state)
        result = subprocess.run(self.command(*self.claim('TEST-001', 'owner-b')),
                                capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.run_ok(*self.claim('TEST-000', 'owner-a'))
        result = subprocess.run(self.command('update', 'TEST-000', '--agent', 'owner-a',
                                            '--status', 'done', '--note', 'missing evidence'),
                                capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.run_ok('update', 'TEST-000', '--agent', 'owner-a', '--status', 'done',
                    '--note', 'isolated current check complete', '--evidence', 'isolated evidence')
        self.run_ok(*self.claim('TEST-001', 'owner-b'))
        (self.folder / 'STATUS.md').write_text('stale', encoding='utf-8')
        result = subprocess.run(self.command('check'), capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.run_ok('render')
        self.run_ok('check')

    def test_new_tasks_are_validated_and_logged(self):
        before = self.read()['revision']
        self.run_ok('add', 'TEST-003', '--agent', 'coordinator', '--note', 'agreed decomposition',
                    '--title', 'separate component', '--milestone', 'COORD',
                    '--scope', 'component-3', '--acceptance', 'observable result', '--next', 'inspect code')
        state = self.read()
        self.assertEqual(state['revision'], before + 1)
        self.assertEqual(state['events'][-1]['action'], 'add')
        self.run_ok(*self.claim('TEST-003', 'client-new'))
        self.run_ok('check')

    @unittest.skipIf(os.name == 'nt', 'POSIX shared-file modes')
    def test_shared_modes_survive_atomic_ledger_and_view_replacement(self):
        targets = [self.folder / 'state.json', *self.folder.glob('*.md')]
        for target in targets:
            target.chmod(0o660)
        self.run_ok(*self.claim('TEST-000', 'shared-client'))
        for target in targets:
            self.assertEqual(target.stat().st_mode & 0o777, 0o660, target.name)
        self.run_ok('check')

    @unittest.skipIf(os.name == 'nt', 'POSIX private-file modes')
    def test_first_generated_views_remain_private(self):
        for target in self.folder.glob('*.md'):
            self.assertEqual(target.stat().st_mode & 0o077, 0, target.name)


if __name__ == '__main__':
    unittest.main()
