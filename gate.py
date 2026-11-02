#!/usr/bin/env python3
"""Review proposed CRM changes locally; export only an explicitly approved batch."""
import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

NAME = r'^[A-Za-z][A-Za-z0-9_]{0,79}$'
SCALAR = {'type': ['string', 'number', 'boolean', 'null']}
VALUES = {'type': 'object', 'minProperties': 1, 'maxProperties': 50,
          'propertyNames': {'pattern': NAME}, 'additionalProperties': SCALAR}
CHANGE = {'type': 'object', 'additionalProperties': False,
          'required': ['object', 'record_id', 'expected', 'updates'], 'properties': {
              'object': {'type': 'string', 'pattern': NAME},
              'record_id': {'type': 'string', 'minLength': 1, 'maxLength': 100},
              'expected': VALUES, 'updates': VALUES}}
PROPOSAL = {'type': 'object', 'additionalProperties': False,
            'required': ['request_id', 'changes'], 'properties': {
                'request_id': {'type': 'string', 'minLength': 1, 'maxLength': 100},
                'changes': {'type': 'array', 'minItems': 1, 'maxItems': 1000, 'items': CHANGE}}}
FIELD_RULE = {'type': 'object', 'additionalProperties': False, 'required': ['type'], 'properties': {
    'type': {'enum': ['string', 'number', 'integer', 'boolean', 'null']},
    'enum': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': SCALAR},
    'minLength': {'type': 'integer', 'minimum': 0, 'maximum': 10000},
    'maxLength': {'type': 'integer', 'minimum': 0, 'maximum': 10000},
    'minimum': {'type': 'number'}, 'maximum': {'type': 'number'}}}
POLICY = {'type': 'object', 'additionalProperties': False, 'required': ['max_changes', 'objects'],
          'properties': {'max_changes': {'type': 'integer', 'minimum': 1, 'maximum': 1000},
                         'objects': {'type': 'object', 'minProperties': 1, 'maxProperties': 30,
                                     'propertyNames': {'pattern': NAME}, 'additionalProperties': {
                                         'type': 'object', 'minProperties': 1, 'maxProperties': 50,
                                         'propertyNames': {'pattern': NAME}, 'additionalProperties': FIELD_RULE}}}}
SNAPSHOT = {'type': 'array', 'maxItems': 5000, 'items': {
    'type': 'object', 'additionalProperties': False, 'required': ['object', 'record_id', 'values'],
    'properties': {'object': {'type': 'string', 'pattern': NAME},
                   'record_id': {'type': 'string', 'minLength': 1, 'maxLength': 100}, 'values': VALUES}}}


class GateError(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GateError('Duplicate JSON key; ambiguous input rejected')
        result[key] = value
    return result


def load(path):
    raw = Path(path).read_bytes()
    if len(raw) > 2_000_000:
        raise GateError('Input exceeds the 2 MB limit')
    def invalid_constant(value):
        raise GateError('Non-finite JSON numbers are not supported')
    parsed = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object,
                        parse_constant=invalid_constant)
    def check_finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise GateError('Non-finite JSON numbers are not supported')
        if isinstance(value, dict):
            for item in value.values():
                check_finite(item)
        elif isinstance(value, list):
            for item in value:
                check_finite(item)
    check_finite(parsed)
    return parsed


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def structural_errors(value, schema, source):
    # Do not expose validator messages: they can include business values.
    return [{'code': 'invalid_' + source, 'path': list(error.absolute_path), 'rule': error.validator}
            for error in Draft202012Validator(schema).iter_errors(value)]


def evaluate(proposal, policy, snapshot):
    errors = structural_errors(proposal, PROPOSAL, 'proposal') + \
             structural_errors(policy, POLICY, 'policy') + structural_errors(snapshot, SNAPSHOT, 'snapshot')
    if errors:
        return errors
    current = {}
    for index, record in enumerate(snapshot):
        key = (record['object'], record['record_id'])
        if key in current:
            errors.append({'code': 'duplicate_snapshot_record', 'record': index})
        current[key] = record['values']
    if len(proposal['changes']) > policy['max_changes']:
        errors.append({'code': 'batch_limit'})
    seen = set()
    for index, change in enumerate(proposal['changes']):
        key = (change['object'], change['record_id'])
        if key in seen:
            errors.append({'code': 'duplicate_proposed_record', 'change': index})
        seen.add(key)
        fields = policy['objects'].get(change['object'])
        if fields is None:
            errors.append({'code': 'object_not_allowed', 'change': index})
            continue
        values = current.get(key)
        if values is None:
            errors.append({'code': 'record_not_found', 'change': index})
            continue
        if set(change['expected']) != set(change['updates']):
            errors.append({'code': 'expected_fields_must_match_updates', 'change': index})
        for field, value in change['updates'].items():
            if field not in fields:
                errors.append({'code': 'field_not_allowed', 'change': index, 'field': field})
                continue
            schema_errors = structural_errors(value, fields[field], 'value')
            if schema_errors:
                errors.append({'code': 'value_outside_policy', 'change': index, 'field': field})
            if field not in change['expected'] or field not in values:
                errors.append({'code': 'missing_expected_value', 'change': index, 'field': field})
            elif digest(values[field]) != digest(change['expected'][field]):
                errors.append({'code': 'stale_expected_value', 'change': index, 'field': field})
            elif digest(value) == digest(values[field]):
                errors.append({'code': 'no_change', 'change': index, 'field': field})
    return errors


def review_hash(proposal, policy, snapshot_hash):
    return digest({'version': 1, 'proposal': proposal, 'policy': policy, 'snapshot_sha256': snapshot_hash})


def write_directory(output, files):
    root = Path(output)
    if root.exists():
        raise GateError('Output already exists; use a new run directory')
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(mode=0o700)
    for name, value in files.items():
        with (root / name).open('x', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')


def plan(proposal, policy, snapshot, output):
    errors = evaluate(proposal, policy, snapshot)
    summary = {'ready_for_review': not errors, 'error_count': len(errors), 'errors': errors,
               'crm_writes': 0}
    files = {'report.json': summary}
    if not errors:
        snapshot_hash = digest(snapshot)
        approval = review_hash(proposal, policy, snapshot_hash)
        summary['approval_hash'] = approval
        summary['change_count'] = len(proposal['changes'])
        files['review.json'] = {'version': 1, 'proposal': proposal, 'policy': policy,
                                'snapshot_sha256': snapshot_hash, 'approval_hash': approval}
    write_directory(output, files)
    return summary


def approve(review, snapshot, approval, output):
    if not isinstance(review, dict) or set(review) != {
            'version', 'proposal', 'policy', 'snapshot_sha256', 'approval_hash'} or review['version'] != 1:
        raise GateError('Unsupported review file')
    expected_hash = review_hash(review['proposal'], review['policy'], review['snapshot_sha256'])
    if approval != expected_hash or review['approval_hash'] != expected_hash:
        raise GateError('Approval hash does not match the reviewed batch')
    if digest(snapshot) != review['snapshot_sha256']:
        raise GateError('Snapshot changed; generate and review a new plan')
    if evaluate(review['proposal'], review['policy'], snapshot):
        raise GateError('Batch no longer passes policy validation')
    payload = {'request_id': review['proposal']['request_id'], 'approval_hash': approval,
               'changes': [{k: c[k] for k in ['object', 'record_id', 'updates']}
                           for c in review['proposal']['changes']]}
    receipt = {'status': 'exported_for_external_review', 'change_count': len(payload['changes']),
               'approval_hash': approval, 'payload_sha256': digest(payload), 'crm_writes': 0}
    write_directory(output, {'approved-changes.json': payload, 'receipt.json': receipt})
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan', help='Validate proposal against policy and a current snapshot')
    p.add_argument('--proposal', required=True)
    p.add_argument('--policy', required=True)
    p.add_argument('--snapshot', required=True)
    p.add_argument('--out', required=True)
    a = sub.add_parser('approve', help='Export an approved batch without writing to any CRM')
    a.add_argument('--review', required=True)
    a.add_argument('--snapshot', required=True)
    a.add_argument('--approve', required=True)
    a.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'plan':
            result = plan(load(args.proposal), load(args.policy), load(args.snapshot), args.out)
        else:
            result = approve(load(args.review), load(args.snapshot), args.approve, args.out)
        print(json.dumps(result, indent=2))
        return 1 if result.get('ready_for_review') is False else 0
    except (GateError, OSError, ValueError, TypeError, RecursionError) as exc:
        # JSON parser errors can expose the source document; emit only a safe code.
        message = str(exc) if isinstance(exc, GateError) else 'Input could not be processed; inspect it locally'
        print(json.dumps({'error': message}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
