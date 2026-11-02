import copy
import json
import tempfile
import unittest
from pathlib import Path

import gate


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.example = json.loads((Path(__file__).parent / 'examples.json').read_text())
        self.p = self.example['proposal']
        self.policy = self.example['policy']
        self.snapshot = self.example['snapshot']
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def errors(self):
        return {e['code'] for e in gate.evaluate(self.p, self.policy, self.snapshot)}

    def reviewed(self):
        report = gate.plan(self.p, self.policy, self.snapshot, self.root / 'plan')
        return gate.load(self.root / 'plan/review.json'), report['approval_hash']

    def test_valid_plan_and_approved_export(self):
        review, approval = self.reviewed()
        receipt = gate.approve(review, self.snapshot, approval, self.root / 'approved')
        self.assertEqual(receipt['change_count'], 1)
        self.assertEqual(receipt['crm_writes'], 0)
        exported = gate.load(self.root / 'approved/approved-changes.json')
        self.assertEqual(exported['changes'][0]['updates']['Status'], 'Working')
        self.assertNotIn('expected', exported['changes'][0])

    def test_unknown_object_and_field_are_denied(self):
        self.p['changes'][0]['object'] = 'User'
        self.assertIn('object_not_allowed', self.errors())
        self.p['changes'][0]['object'] = 'Lead'
        self.p['changes'][0]['updates']['OwnerId'] = 'not-permitted'
        self.assertIn('field_not_allowed', self.errors())

    def test_schema_types_and_enum_are_enforced(self):
        for field, value in [('Score__c', True), ('Score__c', 101), ('Status', 'Deleted')]:
            with self.subTest(field=field, value=value):
                proposal = copy.deepcopy(self.p)
                proposal['changes'][0]['updates'][field] = value
                errors = gate.evaluate(proposal, self.policy, self.snapshot)
                self.assertIn('value_outside_policy', {e['code'] for e in errors})

    def test_all_updated_fields_need_expected_values(self):
        del self.p['changes'][0]['expected']['Status']
        self.assertIn('expected_fields_must_match_updates', self.errors())
        self.assertIn('missing_expected_value', self.errors())

    def test_stale_expectation_blocks_entire_batch(self):
        self.p['changes'][0]['expected']['Status'] = 'Qualified'
        self.assertIn('stale_expected_value', self.errors())
        report = gate.plan(self.p, self.policy, self.snapshot, self.root / 'blocked')
        self.assertFalse(report['ready_for_review'])
        self.assertFalse((self.root / 'blocked/review.json').exists())

    def test_duplicate_records_and_batch_limits(self):
        self.p['changes'].append(copy.deepcopy(self.p['changes'][0]))
        self.policy['max_changes'] = 1
        self.assertIn('duplicate_proposed_record', self.errors())
        self.assertIn('batch_limit', self.errors())
        self.snapshot.append(copy.deepcopy(self.snapshot[0]))
        self.assertIn('duplicate_snapshot_record', self.errors())

    def test_missing_record_and_noop_are_rejected(self):
        self.snapshot[0]['record_id'] = 'another'
        self.assertIn('record_not_found', self.errors())
        self.snapshot[0]['record_id'] = 'demo-lead-001'
        self.p['changes'][0]['updates']['Status'] = 'Open'
        self.assertIn('no_change', self.errors())

    def test_remote_schema_references_are_not_accepted(self):
        self.policy['objects']['Lead']['Status']['$ref'] = 'https://example.invalid/schema'
        self.assertIn('invalid_policy', self.errors())

    def test_snapshot_drift_after_review_prevents_export(self):
        review, approval = self.reviewed()
        self.snapshot[0]['values']['Score__c'] = 21
        with self.assertRaises(gate.GateError):
            gate.approve(review, self.snapshot, approval, self.root / 'approved')
        self.assertFalse((self.root / 'approved').exists())

    def test_wrong_hash_and_tampered_review_prevent_export(self):
        review, approval = self.reviewed()
        with self.assertRaises(gate.GateError):
            gate.approve(review, self.snapshot, 'bad-hash', self.root / 'approved')
        review['proposal']['changes'][0]['updates']['Score__c'] = 99
        with self.assertRaises(gate.GateError):
            gate.approve(review, self.snapshot, approval, self.root / 'approved')

    def test_existing_output_is_not_overwritten(self):
        review, approval = self.reviewed()
        gate.approve(review, self.snapshot, approval, self.root / 'approved')
        before = (self.root / 'approved/approved-changes.json').read_bytes()
        with self.assertRaises(gate.GateError):
            gate.approve(review, self.snapshot, approval, self.root / 'approved')
        self.assertEqual(before, (self.root / 'approved/approved-changes.json').read_bytes())

    def test_machine_report_does_not_include_business_values(self):
        self.p['changes'][0]['updates']['Status'] = 'confidential-business-value'
        report = gate.plan(self.p, self.policy, self.snapshot, self.root / 'blocked')
        self.assertNotIn('confidential-business-value', json.dumps(report))

    def test_strict_json_rejects_duplicates_and_nonfinite_numbers(self):
        for raw in ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1e9999}']:
            with self.subTest(raw=raw):
                source = self.root / 'bad.json'
                source.write_text(raw)
                with self.assertRaises(gate.GateError):
                    gate.load(source)

    def test_review_hash_is_deterministic_and_policy_bound(self):
        current = gate.digest(self.snapshot)
        first = gate.review_hash(self.p, self.policy, current)
        self.assertEqual(first, gate.review_hash(copy.deepcopy(self.p), copy.deepcopy(self.policy), current))
        self.policy['max_changes'] += 1
        self.assertNotEqual(first, gate.review_hash(self.p, self.policy, current))


if __name__ == '__main__':
    unittest.main()
