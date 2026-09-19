"""Temporary branch-only read-only workbench. No credentials or live services."""
from pathlib import Path
import subprocess

assert subprocess.check_output(['git','status','--porcelain'], text=True).strip() == ''
print('BASELINE', subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(), flush=True)
subprocess.run(['python','-m','pytest','tests/','--ignore=tests/test_pwa_retention.py','-q'], check=True)
subprocess.run(['npm','test','--','--exclude','tests/retention.spec.ts'], cwd='pwa', check=True)
for command, cwd in [(['python','-m','pytest','tests/test_pwa_retention.py','-q'], None),
                     (['npm','test','--','tests/retention.spec.ts'], 'pwa')]:
    result = subprocess.run(command, cwd=cwd)
    assert result.returncode == 1, f'Expected a genuine failing assertion for {command}, got {result.returncode}'
print('RED REGRESSIONS VERIFIED', flush=True)
for filename in ['shenyu_gateway/store/_messages.py','admin/src/api/sessions.ts','pwa/src/session/useComposer.ts','pwa/src/api/useUpstream.ts']:
    print('\nSOURCE', filename, flush=True)
    print(Path(filename).read_text(), flush=True)
for filename, terms in {
  'shenyu_gateway/tool_loop.py': ['log_tool_result','reply_version_id','tool_end'],
  'shenyu_gateway/schemas.py': ['SessionDeleteRequest','SessionRenameRequest'],
  'admin/src/views/SessionsView.vue': ['deleteSession','deleteGatewaySession','删除线程','删除会话'],
  'tests/test_gateway_store.py': ['delete_session','deleteGatewaySession','delete_session'],
  'README.md': ['PWA chat frontend','session/persistence','session/reconcile','Maintenance Map'],
  'docs/architecture/REQUEST_CONTEXT.md': ['Transcript identity and recovery','External Frontend Contracts'],
  'docs/architecture/SYSTEM_ZONES.md': ['PWA','会话'],
}.items():
    lines = Path(filename).read_text().splitlines()
    selected = set()
    for i, line in enumerate(lines):
        if any(term in line for term in terms):
            selected.update(range(max(0,i-4),min(len(lines),i+24)))
    print('\nEXCERPTS',filename,flush=True)
    for i in sorted(selected): print(f'{i+1}: {lines[i]}',flush=True)
