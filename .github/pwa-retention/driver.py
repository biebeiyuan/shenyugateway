from pathlib import Path
source = Path('.github/pwa-retention/work.py').read_text()
old = '@click="deleteSessionAction(sessionActionTarget)">删除</button>'
assert source.count(old) == 1
source = source.replace(old, '@click="deleteSessionAction(sessionActionTarget)"\\n          >删除</button>')
source = source.replace("assert receipt['content'] == '{\"ok\":false}'", "assert __import__('json').loads(receipt['content']) == {'ok': False}")
# The real recovery endpoint always includes user_content. Old unit fixtures
# omitted it; supply that existing contract without weakening the new guard.
addition = '''
replace('pwa/tests/reconcile.spec.ts',
    'applyReconciledTail, applyReplyRecovery, tailNeedsReconcile',
    'applyReconciledTail, applyReplyRecovery as recoverReply, tailNeedsReconcile')
replace('pwa/tests/reconcile.spec.ts', 'function payloadOf(',
    "function applyReplyRecovery(messages: UiMessage[], payload: Record<string, unknown>): boolean {\\n"
    "  const user = [...messages].reverse().find(message => message.role === 'user')\\n"
    "  return recoverReply(messages, { user_content: user?.content, ...payload })\\n"
    "}\\n\\nfunction payloadOf(")
put('pwa/tests/retention.spec.ts', Path('pwa/tests/retention.spec.ts').read_text() + "\\n"
    "it('requires a user anchor when neither side has a local reply identity', () => {\\n"
    "  const messages = [message('user', 'question', 'u'), { ...message('assistant', 'partial', 'r'), replyVersionId: undefined, archiveEvent: undefined }]\\n"
    "  expect(applyReplyRecovery(messages, { replies: [{ content: 'partial and complete' }] })).toBe(false)\\n"
    "  expect(messages[1].content).toBe('partial')\\n"
    "})\\n")
'''
source = source.replace('# Fresh full verification;', addition + '\n# Fresh full verification;')
exec(compile(source, '.github/pwa-retention/work.py', 'exec'), {'__name__': '__main__'})
