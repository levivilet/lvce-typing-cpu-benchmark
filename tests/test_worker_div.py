"""Exercise the real worker protocol without Electron startup overhead."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkerDivTests(unittest.TestCase):
    def test_renderer_bridge_readiness_cursor_and_serialized_saves(self):
        subprocess.run(['node', 'tests/worker_div_renderer.cjs'], cwd=ROOT, check=True, capture_output=True)

    def run_worker(self, messages):
        script = """
const fs = require('node:fs');
const vm = require('node:vm');
const results = [];
const self = {postMessage: message => results.push(message)};
vm.runInNewContext(fs.readFileSync('worker-div-electron/worker.js', 'utf8'), {self});
for (const data of JSON.parse(process.argv[1])) self.onmessage({data});
console.log(JSON.stringify(results));
"""
        result = subprocess.run(['node', '-e', script, json.dumps(messages)],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_ordered_input_and_save_snapshot_with_cursor(self):
        results = self.run_worker([
            {'sequence': 1, 'type': 'initialize', 'text': 'fixture\n'},
            {'sequence': 2, 'type': 'select-all'},
            {'sequence': 3, 'type': 'backspace'},
            {'sequence': 4, 'type': 'insert', 'text': 'abc\ndef'},
            {'sequence': 5, 'type': 'left'},
            {'sequence': 6, 'type': 'insert', 'text': 'X'},
            {'sequence': 7, 'type': 'save'},
            {'sequence': 8, 'type': 'insert', 'text': 'Y'},
            {'sequence': 9, 'type': 'save'},
        ])
        self.assertEqual(results[2]['text'], '')
        self.assertEqual(results[6]['text'], 'abc\ndeXf')
        self.assertEqual((results[6]['row'], results[6]['column']), (1, 3))
        self.assertEqual(results[8]['text'], 'abc\ndeXYf')
        self.assertFalse(any('error' in result for result in results))

    def test_rejects_input_before_initialization(self):
        results = self.run_worker([{'sequence': 1, 'type': 'insert', 'text': 'a'}])
        self.assertEqual(results[0]['error'], 'Input before initialization')

    def test_rejects_skipped_or_duplicate_input_sequence(self):
        for sequence in (1, 3):
            results = self.run_worker([
                {'sequence': 1, 'type': 'initialize', 'text': ''},
                {'sequence': sequence, 'type': 'insert', 'text': 'a'},
            ])
            self.assertEqual(results[1]['error'], 'Out-of-order input')

    def test_empty_document_cursor_is_at_origin(self):
        results = self.run_worker([
            {'sequence': 1, 'type': 'initialize', 'text': ''},
            {'sequence': 2, 'type': 'backspace'},
        ])
        self.assertEqual((results[1]['row'], results[1]['column']), (0, 0))
