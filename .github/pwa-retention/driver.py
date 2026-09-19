from pathlib import Path
source = Path('.github/pwa-retention/work.py').read_text()
old = '@click="deleteSessionAction(sessionActionTarget)">删除</button>'
assert source.count(old) == 1
source = source.replace(old, '@click="deleteSessionAction(sessionActionTarget)"\\n          >删除</button>')
source = source.replace("assert receipt['content'] == '{\"ok\":false}'", "assert __import__('json').loads(receipt['content']) == {'ok': False}")
try:
    exec(compile(source, '.github/pwa-retention/work.py', 'exec'), {'__name__': '__main__'})
except Exception:
    for filename, needles in {
        'pwa/src/App.vue': ['setSessionHiddenAction(sessionActionTarget)', 'deleteSessionAction(sessionActionTarget)'],
        'README.md': ['toolHydration.ts'],
        'pwa/src/types.ts': ['GatewaySession'],
        'shenyu_gateway/tool_loop.py': ['log_tool_result'],
    }.items():
        print('DIAGNOSTIC', filename, flush=True)
        lines = Path(filename).read_text().splitlines()
        selected = set()
        for i, line in enumerate(lines):
            if any(needle in line for needle in needles):
                selected.update(range(max(0, i-3), min(len(lines), i+10)))
        for i in sorted(selected): print(f'{i+1}: {lines[i]}', flush=True)
    raise
