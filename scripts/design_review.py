#!/usr/bin/env python3
"""Review, authorize, and verify one bounded code-edit cycle (Python 3.9+)."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import selectors
import time
import subprocess
import sys
import tempfile
import uuid


class ReviewError(Exception):
    pass


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse(data):
    def constant(s):
        raise ValueError('invalid JSON constant: ' + s)
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('duplicate JSON key: ' + k)
            result[k] = v
        return result
    try:
        return json.loads(data, parse_constant=constant, object_pairs_hook=pairs)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ReviewError('invalid JSON: ' + str(exc)) from exc


def path(root, name, existing=True):
    if not isinstance(name, str) or not name or '\0' in name:
        raise ReviewError('invalid path')
    p = Path(name)
    if p.is_absolute() or '..' in p.parts or str(p) in ('', '.'):
        raise ReviewError('path must be relative to root without ..')
    current = root
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise ReviewError('symlink path forbidden: ' + name)
    if existing and not current.is_file():
        raise ReviewError('file missing: ' + name)
    if not existing and current.exists() and not current.is_file():
        raise ReviewError('path must be a file: ' + name)
    return current


def atomic_write(p, data, mode=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.design-review-', dir=str(p.parent))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save(p, state):
    state.pop('state_hash', None)
    state['state_hash'] = sha(encoded(state))
    atomic_write(p, encoded(state) + b'\n')


def load(p):
    state = parse(p.read_bytes())
    if not isinstance(state, dict) or not isinstance(state.get('state_hash'), str):
        raise ReviewError('invalid state')
    expected = state.pop('state_hash')
    if sha(encoded(state)) != expected:
        raise ReviewError('state hash mismatch')
    return state


def snapshots(root, names):
    return {n: sha(path(root, n).read_bytes()) for n in sorted(set(names))}


def assert_hashes(root, hashes):
    for name, expected in hashes.items():
        if sha(path(root, name).read_bytes()) != expected:
            raise ReviewError('observed file changed: ' + name)


def checker_sources(root, args):
    result = []
    for arg in args[1:]:
        if arg.startswith('-'):
            continue
        p = Path(arg)
        if p.is_absolute():
            try:
                arg = str(p.relative_to(root))
            except ValueError:
                continue
        if '..' in Path(arg).parts:
            raise ReviewError('checker argument contains path traversal')
        candidate = path(root, arg, existing=False)
        if candidate.is_file():
            result.append(arg)
    return result


def read_contract(root, contract_name):
    c = parse(path(root, contract_name).read_bytes())
    if not isinstance(c, dict):
        raise ReviewError('contract must be an object')
    edits, inputs, args = c.get('editable_files'), c.get('inputs'), c.get('checker')
    if not isinstance(edits, list) or not edits or not isinstance(inputs, list) or any(not isinstance(x, str) for x in edits + inputs):
        raise ReviewError('invalid editable_files or inputs')
    if not isinstance(args, list) or not args or any(not isinstance(x, str) or not x for x in args):
        raise ReviewError('checker must be a nonempty argument list')
    if c.get('checker_sandbox', 'none') not in ('none', 'macos-read-only'):
        raise ReviewError('unsupported checker_sandbox')
    timeout = c.get('checker_timeout', 30)
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise ReviewError('checker_timeout must be an integer from 1 to 300')
    editable = [path(root, n) for n in edits]
    other_names = [contract_name] + inputs + checker_sources(root, args)
    protected = [path(root, n) for n in other_names]
    # samefile also catches hard-link aliases, not only normalized paths.
    for i, p in enumerate(editable):
        if any(os.path.samefile(p, q) for q in editable[:i] + protected):
            raise ReviewError('editable file aliases another editable or protected file')
    return c, other_names


def bounded_run(args, root, timeout, env=None):
    """Capture at most 1 MiB per stream and kill the process group on limit/timeout."""
    proc = subprocess.Popen(args, cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    selector = selectors.DefaultSelector()
    output = {'stdout': bytearray(), 'stderr': bytearray()}
    for name in output:
        selector.register(getattr(proc, name), selectors.EVENT_READ, name)
    deadline = time.monotonic() + timeout
    error = None
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                error = 'checker timed out'
                break
            for key, _ in selector.select(remaining):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                buf = output[key.data]
                limit = 1024 * 1024
                remaining_capacity = limit - len(buf)
                buf.extend(chunk[:remaining_capacity])
                if len(chunk) > remaining_capacity:
                    error = 'checker output limit exceeded'
                    break
            if error:
                break
        if error:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        try:
            proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            error = 'checker timed out'
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            proc.wait()
    finally:
        selector.close()
        for stream in (proc.stdout, proc.stderr):
            if not stream.closed: stream.close()
    return bytes(output['stdout']), bytes(output['stderr']), proc.returncode, error


def sandbox_run(root, c, tracked):
    sandbox = shutil.which('sandbox-exec')
    if sys.platform != 'darwin' or not sandbox:
        raise OSError('macOS sandbox-exec is unavailable')
    # The checker sees only declared project files, under a fresh temporary root.
    with tempfile.TemporaryDirectory(prefix='design-check-', dir='/private/tmp') as temp:
        stage = Path(temp)
        for name in sorted(set(tracked)):
            source = path(root, name)
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        args = []
        for i, arg in enumerate(c['checker']):
            p = Path(arg)
            if i and p.is_absolute():
                try:
                    name = str(p.relative_to(root))
                except ValueError:
                    raise ReviewError('sandbox checker argument outside root: ' + arg)
                if name not in tracked:
                    raise ReviewError('sandbox checker argument is not tracked: ' + arg)
                arg = str(stage / name)
            elif not i and not p.is_absolute():
                raise ReviewError('sandbox checker executable must be absolute')
            args.append(arg)
        home = json.dumps(str(Path.home()))
        policy = '(version 1) (allow default) (deny network*) (deny file-write*) (deny file-read* (subpath ' + home + '))'
        env = {'PATH': os.defpath, 'TMPDIR': temp, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONIOENCODING': 'utf-8'}
        return bounded_run([sandbox, '-p', policy] + args, stage, c.get('checker_timeout', 30), env)


def run_checker(root, c, tracked):
    before = snapshots(root, tracked)
    out, err, code, error = b'', b'', None, None
    try:
        if c.get('checker_sandbox', 'none') == 'macos-read-only':
            out, err, code, error = sandbox_run(root, c, tracked)
        else:
            out, err, code, error = bounded_run(c['checker'], root, c.get('checker_timeout', 30))
    except (OSError, ReviewError) as exc:
        error = 'checker could not start: ' + str(exc)
    evidence = {'stdout': out.decode('utf-8', 'replace'), 'stderr': err.decode('utf-8', 'replace'), 'stdout_sha256': sha(out), 'stderr_sha256': sha(err), 'exit_code': code}
    try:
        if snapshots(root, tracked) != before:
            error = 'checker mutated observed files'
    except (ReviewError, OSError):
        error = 'checker mutated observed files'
    if not error and code != 0:
        error = 'checker exited with status ' + str(code)
    if not error:
        try:
            report = parse(out)
            if not isinstance(report, dict) or type(report.get('passed')) is not bool or not isinstance(report.get('checks'), list) or not report['checks']:
                raise ReviewError('malformed checker report or empty checks')
            ids = set()
            for check in report['checks']:
                if not isinstance(check, dict) or not isinstance(check.get('id'), str) or not check['id'].strip() or check['id'] in ids or type(check.get('passed')) is not bool or not isinstance(check.get('detail'), str):
                    raise ReviewError('malformed checker check or duplicate id')
                ids.add(check['id'])
            if report['passed'] != all(x['passed'] for x in report['checks']):
                raise ReviewError('checker overall result contradicts checks')
            evidence['report'] = report
        except ReviewError as exc:
            error = str(exc)
    evidence['error'] = error
    return evidence


def context(root, state_name):
    state_path = path(root, state_name)
    state = load(state_path)
    if state.get('root') != str(root):
        raise ReviewError('state belongs to another root')
    return state_path, state


def validate_proposal(p, c):
    if not isinstance(p, dict) or set(p) != {'summary', 'issues', 'questions', 'change_files', 'verification_plan'} or not isinstance(p['summary'], str):
        raise ReviewError('malformed proposal')
    if not isinstance(p['issues'], list):
        raise ReviewError('malformed issues')
    for issue in p['issues']:
        if not isinstance(issue, dict) or set(issue) != {'kind', 'evidence', 'description', 'recommendation'} or issue['kind'] not in ('objective', 'constraint', 'implementation', 'uncertainty') or any(not isinstance(issue[k], str) for k in ('evidence', 'description', 'recommendation')):
            raise ReviewError('malformed issue')
    for key in ('questions', 'change_files', 'verification_plan'):
        if not isinstance(p[key], list) or any(not isinstance(x, str) for x in p[key]):
            raise ReviewError('malformed ' + key)
    if len(set(p['change_files'])) != len(p['change_files']) or any(x not in c['editable_files'] for x in p['change_files']):
        raise ReviewError('change_files must be distinct declared editable files')


def inspect(root, contract_name, state_name):
    c, protected = read_contract(root, contract_name)
    observed = c['editable_files'] + protected
    state_path = path(root, state_name, existing=False)
    if state_path.exists():
        raise ReviewError('state already exists; use a new path')
    if state_path.resolve() in [path(root, n).resolve() for n in observed]:
        raise ReviewError('state collides with observed file')
    originals = {n: {'bytes_base64': base64.b64encode(path(root, n).read_bytes()).decode(), 'mode': path(root, n).stat().st_mode & 0o777} for n in c['editable_files']}
    hashes = snapshots(root, observed)
    check = run_checker(root, c, observed)
    if check['error']:
        return {'failure': 'checker_error', 'error': check['error'], 'check': check}
    assert_hashes(root, hashes)
    state = {'version': 1, 'id': str(uuid.uuid4()), 'root': str(root), 'contract': contract_name, 'hashes': hashes, 'originals': originals, 'protected': sorted(set(protected)), 'phase': 'inspected', 'inspection': check}
    save(state_path, state)
    return {'state_id': state['id'], 'state_hash': state['state_hash'], 'phase': state['phase'], 'check': check, 'hashes': hashes}


def propose(root, state_name, proposal_name):
    state_path, state = context(root, state_name)
    if state['phase'] != 'inspected':
        raise ReviewError('state is not inspected')
    assert_hashes(root, state['hashes'])
    c, _ = read_contract(root, state['contract'])
    pp = path(root, proposal_name)
    if os.path.samefile(pp, state_path) or any(os.path.samefile(pp, path(root, n)) for n in state['hashes']):
        raise ReviewError('proposal must be separate from observed files and state')
    raw = pp.read_bytes()
    proposal = parse(raw)
    validate_proposal(proposal, c)
    state.update(phase='waiting_decision', proposal=proposal, proposal_file=proposal_name, proposal_hash=sha(raw))
    save(state_path, state)
    return {'state_id': state['id'], 'state_hash': state['state_hash'], 'phase': state['phase'], 'proposal_hash': state['proposal_hash'], 'proposal': proposal}


def proposal_unchanged(root, state):
    raw = path(root, state['proposal_file']).read_bytes()
    if sha(raw) != state['proposal_hash'] or parse(raw) != state['proposal']:
        raise ReviewError('proposal file changed')


def decide(root, state_name, choice, reason, actor):
    if choice not in ('approve', 'reject') or actor not in ('human', 'simulated') or not isinstance(reason, str) or not reason.strip():
        raise ReviewError('invalid decision')
    sp, state = context(root, state_name)
    if state['phase'] != 'waiting_decision':
        raise ReviewError('state is not waiting for a decision')
    assert_hashes(root, state['hashes'])
    proposal_unchanged(root, state)
    state['decision'] = {'choice': choice, 'reason': reason, 'actor': actor, 'proposal_hash': state['proposal_hash'], 'observed_hashes': state['hashes'].copy()}
    state['phase'] = 'approved' if choice == 'approve' else 'rejected'
    save(sp, state)
    return {'state_id': state['id'], 'state_hash': state['state_hash'], 'phase': state['phase'], 'decision': state['decision']}


def begin(root, state_name):
    sp, state = context(root, state_name)
    if state['phase'] != 'approved':
        raise ReviewError('approved decision required')
    assert_hashes(root, state['hashes'])
    proposal_unchanged(root, state)
    decision = state['decision']
    if decision['choice'] != 'approve' or decision['proposal_hash'] != state['proposal_hash'] or decision['observed_hashes'] != state['hashes']:
        raise ReviewError('decision binding mismatch')
    state['phase'] = 'editing'
    save(sp, state)
    return {'state_id': state['id'], 'state_hash': state['state_hash'], 'phase': state['phase'], 'change_files': state['proposal']['change_files']}


def verify(root, state_name):
    sp, state = context(root, state_name)
    if state['phase'] != 'editing':
        raise ReviewError('editing phase required')
    check, error = None, None
    try:
        proposal_unchanged(root, state)
        assert_hashes(root, {n: state['hashes'][n] for n in state['protected']})
        c, protected = read_contract(root, state['contract'])
        for n in c['editable_files']:
            if n not in state['proposal']['change_files']:
                assert_hashes(root, {n: state['hashes'][n]})
        check = run_checker(root, c, c['editable_files'] + protected)
        if check['error']:
            raise ReviewError(check['error'])
        if not check['report']['passed']:
            raise ReviewError('checker reported failure')
    except (ReviewError, OSError, ValueError, KeyError, TypeError) as exc:
        error = str(exc)
    if error:
        # All declared editable files are restored; a hostile symlink is not followed.
        for n, original in state['originals'].items():
            atomic_write(path(root, n, existing=False), base64.b64decode(original['bytes_base64'], validate=True), original['mode'])
        state['phase'] = 'rolled_back'
    else:
        state['phase'] = 'verified'
    state['verification'] = {'check': check, 'error': error, 'editable_hashes': snapshots(root, list(state['originals']))}
    save(sp, state)
    return {'state_id': state['id'], 'state_hash': state['state_hash'], 'phase': state['phase'], 'verification': state['verification']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'propose', 'decide', 'begin', 'verify'):
        p = sub.add_parser(name)
        p.add_argument('--root', required=True)
        p.add_argument('--state', required=True)
        if name == 'inspect': p.add_argument('--contract', required=True)
        if name == 'propose': p.add_argument('--proposal', required=True)
        if name == 'decide':
            p.add_argument('--choice', choices=('approve', 'reject'), required=True)
            p.add_argument('--actor', choices=('human', 'simulated'), required=True)
            p.add_argument('--reason', required=True)
    a = parser.parse_args(argv)
    try:
        root = Path(a.root).resolve(strict=True)
        if not root.is_dir(): raise ReviewError('root must be a directory')
        if a.command == 'inspect': result = inspect(root, a.contract, a.state)
        elif a.command == 'propose': result = propose(root, a.state, a.proposal)
        elif a.command == 'decide': result = decide(root, a.state, a.choice, a.reason, a.actor)
        elif a.command == 'begin': result = begin(root, a.state)
        else: result = verify(root, a.state)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 2 if result.get('phase') == 'rolled_back' else (1 if result.get('failure') else 0)
    except (ReviewError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
