"""Apply hash-checked, locally tested source edits in an isolated feature checkout."""
from pathlib import Path
import base64
import hashlib
import json
import lzma
import os
import subprocess

BRANCH = 'fix/pwa-record-retention'
assert os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH
assert subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == BRANCH
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == os.environ['GITHUB_SHA']
assert not subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()
root = Path.cwd().resolve()
encoded = ''.join(Path(f'.github/pwa-retention/part{n}.xz64').read_text() for n in (1, 2))
raw = lzma.decompress(base64.b64decode(encoded, validate=True))
assert hashlib.sha256(raw).hexdigest() == '49763971c1b2f423df6525fec0b8714a320fdbcccf0dd436ec17e34c796917ea'
edits = json.loads(raw)
assert len(edits) == 23
outputs = {}
for entry in edits:
    path = Path(entry['path'])
    assert not path.is_absolute() and '..' not in path.parts
    assert path.as_posix() not in outputs
    assert path.as_posix() == 'README.md' or path.as_posix() == 'project_delivery_log.jsonl' or path.parts[0] in {'pwa', 'admin', 'shenyu_gateway', 'tests', 'docs'}
    old = path.read_bytes() if path.exists() else None
    assert (hashlib.sha256(old).hexdigest() if old is not None else None) == entry['old'], f'Stale input: {path}'
    lines = old.decode('utf-8').splitlines(keepends=True) if old is not None else []
    for start, end, replacement in reversed(entry['edits']):
        assert 0 <= start <= end <= len(lines)
        lines[start:end] = replacement.splitlines(keepends=True)
    output = ''.join(lines).encode('utf-8')
    assert hashlib.sha256(output).hexdigest() == entry['new'], f'Corrupt output: {path}'
    outputs[path.as_posix()] = output
# Validate the complete payload before touching any file.
for name, content in outputs.items():
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
print('APPLIED_VERIFIED_PAYLOAD', len(outputs), flush=True)
for name in sorted(outputs):
    if name.endswith('.py'):
        subprocess.run(['python', '-m', 'py_compile', name], check=True)
commands = [
    (['python', '-m', 'pytest', 'tests/', '-q'], None),
    (['npm', 'test'], 'pwa'),
    (['npm', 'run', 'build'], 'pwa'),
    (['npm', 'test'], 'admin'),
    (['npm', 'run', 'build'], 'admin'),
    (['npx', 'playwright', 'test'], 'admin'),
    (['python', 'scripts/resident_home.py', 'check'], None),
]
failures = []
for command, cwd in commands:
    print('VERIFY', command, 'cwd', cwd, flush=True)
    result = subprocess.run(command, cwd=cwd)
    if result.returncode:
        failures.append((command, result.returncode))
assert not failures, f'Product commit withheld: {failures}'
subprocess.run(['git', 'diff', '--check'], check=True)
# The temporary editor cannot become part of the delivered runtime tree.
controls = [
    '.github/workflows/pwa-retention-workbench.yml',
    '.github/pwa-retention/driver.py', '.github/pwa-retention/work.py',
    '.github/pwa-retention/toolHydration.ts',
    '.github/pwa-retention/part1.xz64', '.github/pwa-retention/part2.xz64',
]
subprocess.run(['git', 'rm', '--', *controls], check=True)
subprocess.run(['git', 'add', '--', *sorted(outputs)], check=True)
subprocess.run(['git', 'diff', '--cached', '--check'], check=True)
subprocess.run(['git', 'diff', '--cached', '--stat'], check=True)
subprocess.run(['git', 'config', 'user.name', 'shenyugateway repair workbench'], check=True)
subprocess.run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], check=True)
subprocess.run(['git', 'commit', '-m', 'fix(pwa): retain complete per-session records across reopen and recovery'], check=True)
subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/' + BRANCH], check=True)
print('VERIFIED_PRODUCT_HEAD', subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), flush=True)
print('VERIFIED_PRODUCT_TREE', subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], text=True).strip(), flush=True)
