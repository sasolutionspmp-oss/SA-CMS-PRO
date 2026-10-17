"""Actual Linux process lifecycle checks; no ERP database, Redis or provider."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'run-distribution-services.py'
spec = importlib.util.spec_from_file_location('distribution_supervisor', SOURCE)
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


@unittest.skipUnless(sys.platform == 'linux', 'Development supervisor uses Linux process sessions')
class DistributionSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='cipher-supervisor-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.processes = []
        self.sessions = set()
        self.addCleanup(self.cleanup_processes)

    def cleanup_processes(self):
        for path in self.root.glob('*.ready'):
            try:
                self.sessions.add(json.loads(path.read_text())['session'])
            except (ValueError, KeyError):
                pass
        for session in self.sessions:
            service.signal_session(session, signal.SIGKILL)
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)

    def wait_for(self, predicate, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.02)
        self.fail('Process did not reach its expected state')

    @staticmethod
    def running(pid):
        try:
            return Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].split()[0] != 'Z'
        except FileNotFoundError:
            return False

    def child(self, name, *, ignore_term=False, grandchild=False):
        path = self.root / (name + '.py')
        child_path = self.root / (name + '-horse.py')
        common = "import os,signal,time,json\nfrom pathlib import Path\n"
        ready = "Path(__file__).with_suffix('.ready').write_text(json.dumps({'pid':os.getpid(),'session':os.getsid(0),'group':os.getpgrp()}))\n"
        if grandchild:
            child_path.write_text(common + "os.setpgrp()\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\n" + ready + 'time.sleep(60)\n')
        script = common
        if ignore_term:
            script += 'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
        if grandchild:
            script += 'import subprocess,sys\nsubprocess.Popen([sys.executable,' + repr(str(child_path)) + '])\n'
        path.write_text(script + ready + 'time.sleep(60)\n')
        return [sys.executable, str(path)]

    def launch(self, commands):
        harness = self.root / 'harness.py'
        harness.write_text('import importlib.util\n'
            + 's=importlib.util.spec_from_file_location("service",' + repr(str(SOURCE)) + ')\n'
            + 'm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
            + 'raise SystemExit(m.supervise(' + repr(commands) + ',cwd=' + repr(str(self.root)) + ',shutdown_timeout=0.3))\n')
        process = subprocess.Popen([sys.executable, str(harness)], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        self.processes.append(process)
        return process

    def ready(self, name):
        path = self.root / (name + '.ready')
        self.wait_for(lambda: path.exists() and path.stat().st_size)
        result = json.loads(path.read_text())
        self.sessions.add(result['session'])
        return result

    def test_sigterm_stops_both_children_and_preserves_unrelated_process(self):
        sentinel = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'], start_new_session=True)
        self.processes.append(sentinel)
        pair = self.launch([self.child('consumer'), self.child('publisher')])
        children = [self.ready('consumer'), self.ready('publisher')]
        self.assertNotEqual(children[0]['session'], children[1]['session'])
        pair.send_signal(signal.SIGTERM)
        self.assertEqual(pair.wait(timeout=5), 0)
        self.assertTrue(all(not self.running(child['pid']) for child in children))
        self.assertIsNone(sentinel.poll())

    def test_unexpected_child_exit_fails_and_stops_sibling(self):
        pair = self.launch([self.child('consumer'), self.child('publisher')])
        consumer, publisher = self.ready('consumer'), self.ready('publisher')
        os.kill(consumer['pid'], signal.SIGKILL)
        self.assertEqual(pair.wait(timeout=5), 1)
        self.assertFalse(self.running(publisher['pid']))

    def test_deadline_kills_separate_work_horse_group(self):
        pair = self.launch([self.child('consumer', ignore_term=True, grandchild=True), self.child('publisher')])
        consumer, horse = self.ready('consumer'), self.ready('consumer-horse')
        self.ready('publisher')
        self.assertEqual(consumer['session'], horse['session'])
        self.assertNotEqual(consumer['group'], horse['group'])
        pair.send_signal(signal.SIGINT)
        self.assertEqual(pair.wait(timeout=5), 0)
        self.wait_for(lambda: not self.running(consumer['pid']) and not self.running(horse['pid']))

    def test_cli_rejects_runtime_targets_before_launch(self):
        result = subprocess.run([sys.executable, str(SOURCE), '--queue', 'other'], capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('accepts no arguments', result.stderr)


if __name__ == '__main__':
    unittest.main()
