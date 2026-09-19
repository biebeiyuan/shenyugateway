"""Temporary isolated branch editor. Never connects to resident services or master."""
from pathlib import Path
import os
import subprocess

BRANCH = 'fix/pwa-record-retention'
assert os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH
assert subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == BRANCH
assert not subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()
start = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
assert start == os.environ['GITHUB_SHA'], 'Branch advanced since this run was queued'
touched = set()

def put(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text)
    touched.add(path)

def replace(path, old, new, count=1):
    text = Path(path).read_text()
    assert text.count(old) == count, f'{path}: expected {count} anchor(s), got {text.count(old)}: {old[:110]}'
    put(path, text.replace(old, new))

def section(path, start_marker, end_marker, replacement):
    text = Path(path).read_text()
    begin = text.index(start_marker)
    end = text.index(end_marker, begin)
    put(path, text[:begin] + replacement + text[end:])

# The nine earlier regressions were proven red in workbench run 35423424775.
# Add a producer-side identity regression and prove it red before that change.
p = 'tests/test_pwa_retention.py'
put(p, Path(p).read_text() + '''

def test_tool_receipt_keeps_real_reply_and_call_identity(tmp_path):
    from shenyu_gateway.sessions import SessionManager
    store = GatewayStore(str(tmp_path / 'runtime.db'))
    session = store.get_or_create_session('receipt', 'shenyu-pwa')
    manager = SessionManager(store, SimpleNamespace())
    manager.log_tool_result(session['id'], 'shenyu_recall', {'q': 'x'}, {'ok': False},
                            reply_version_id='reply-a', tool_call_id='call-a')
    receipt = store.get_recent_messages(session['id'])[0]
    assert receipt['reply_version_id'] == 'reply-a'
    assert receipt['tool_call_id'] == 'call-a'
    assert receipt['content'] == '{"ok":false}'
''')
red = subprocess.run(['python', '-m', 'pytest', p, '-k', 'tool_receipt', '-q'])
assert red.returncode == 1, 'Expected missing producer identity contract to fail'

# Session visibility is display state only. Existing internal callers default to all.
replace('shenyu_gateway/store/_base.py',
    '            self._ensure_column(conn, "gateway_sessions", "display_name", "TEXT")',
    '            self._ensure_column(conn, "gateway_sessions", "display_name", "TEXT")\n'
    '            self._ensure_column(conn, "gateway_sessions", "hidden_at", "TEXT")\n'
    '            self._ensure_column(conn, "gateway_messages", "reply_version_id", "TEXT")\n'
    '            self._ensure_column(conn, "gateway_messages", "tool_call_id", "TEXT")\n'
    '            conn.execute("CREATE INDEX IF NOT EXISTS idx_gateway_messages_reply "\n'
    '                         "ON gateway_messages(session_id, reply_version_id)")')
replace('shenyu_gateway/store/_sessions.py',
    'def list_sessions(self, limit: int = 100, query: str = "") -> list[dict]:',
    'def list_sessions(self, limit: int = 100, query: str = "", visibility: str = "all") -> list[dict]:')
replace('shenyu_gateway/store/_sessions.py',
    '''        where = "WHERE s.session_tag LIKE ? OR COALESCE(s.client_name, '') LIKE ?"
        params: tuple[Any, ...] = (pattern, pattern, limit) if query.strip() else (limit,)''',
    '''        if visibility not in {"all", "visible", "hidden"}:
            raise ValueError("invalid session visibility")
        clauses = []
        params: list[Any] = []
        if query.strip():
            clauses.append("(s.session_tag LIKE ? OR COALESCE(s.client_name, '') LIKE ?)")
            params.extend((pattern, pattern))
        if visibility != "all":
            clauses.append("s.hidden_at IS " + ("NOT NULL" if visibility == "hidden" else "NULL"))
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)''')
replace('shenyu_gateway/store/_sessions.py', '{where if query.strip() else ""}', '{where}')
replace('shenyu_gateway/store/_sessions.py',
    '    def get_session_by_tag(self, session_tag: str) -> Optional[dict]:',
    '''    def set_session_visibility(self, session_id: str, hidden: bool) -> Optional[dict]:
        """Organize the PWA list; never change activity, context or resident records."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE gateway_sessions SET hidden_at = "
                "CASE WHEN ? THEN COALESCE(hidden_at, ?) ELSE NULL END WHERE id = ?",
                (hidden, iso_now(), session_id),
            )
            row = conn.execute("SELECT * FROM gateway_sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(row) if row else None

    def get_session_by_tag(self, session_tag: str) -> Optional[dict]:''')
replace('shenyu_gateway/schemas.py', 'class SessionRenameRequest(BaseModel):',
    'class SessionVisibilityRequest(BaseModel):\n    hidden: bool = Field(strict=True)\n\n\nclass SessionRenameRequest(BaseModel):')
replace('shenyu_gateway/gateway_admin_routes.py', 'from typing import Any, Callable, Optional',
        'from typing import Any, Callable, Literal, Optional')
replace('shenyu_gateway/gateway_admin_routes.py', '    SessionRenameRequest,',
        '    SessionRenameRequest,\n    SessionVisibilityRequest,')
replace('shenyu_gateway/gateway_admin_routes.py',
    'async def list_gateway_sessions(limit: int = 100, q: str = ""):',
    'async def list_gateway_sessions(limit: int = 100, q: str = "", visibility: Literal["all", "visible", "hidden"] = "all"):')
replace('shenyu_gateway/gateway_admin_routes.py',
    'sessions = store.list_sessions(limit=limit, query=q)',
    'sessions = store.list_sessions(limit=limit, query=q, visibility=visibility)')
section('shenyu_gateway/gateway_admin_routes.py',
    '    @router.delete("/api/gateway/sessions/{session_tag}")',
    '    @router.get("/api/gateway/logs")',
    '''    @router.patch("/api/gateway/sessions/{session_tag}/visibility")
    async def set_gateway_session_visibility(session_tag: str, body: SessionVisibilityRequest):
        store = deps.require_session_store()
        session = store.get_session_by_tag(session_tag)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found.")
        updated = store.set_session_visibility(session["id"], body.hidden)
        return {"ok": True, "session": updated}

    @router.delete("/api/gateway/sessions/{session_tag}")
    async def delete_gateway_session(session_tag: str, body: SessionDeleteRequest):
        # Cached PWA/Admin bundles can still send the old request. A browser
        # conversation-list action must never delete the shared heartbeat pool.
        raise HTTPException(status_code=409, detail="旧版删除入口已停用，请更新页面后使用收起对话。所有记录都未删除。")

''')

# Preserve original tool execution semantics; add only stable receipt association.
replace('shenyu_gateway/store/_messages.py',
    '        source_id: Optional[str] = None,\n',
    '        source_id: Optional[str] = None,\n        reply_version_id: Optional[str] = None,\n        tool_call_id: Optional[str] = None,\n')
replace('shenyu_gateway/store/_messages.py',
    'tool_result_summary, source_table, source_id, created_at\n                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    'tool_result_summary, source_table, source_id, created_at, reply_version_id, tool_call_id\n                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
replace('shenyu_gateway/store/_messages.py',
    '                    source_id,\n                    iso_now(),',
    '                    source_id,\n                    iso_now(),\n                    reply_version_id,\n                    tool_call_id,')
replace('shenyu_gateway/sessions.py',
    'def log_tool_result(self, session_id: str, tool_name: str, args: dict, result: dict):',
    'def log_tool_result(self, session_id: str, tool_name: str, args: dict, result: dict, *,\n                        reply_version_id: str = "", tool_call_id: str = ""):')
replace('shenyu_gateway/sessions.py',
    '            tool_result_summary=shorten(content, 200),',
    '            tool_result_summary=shorten(content, 200),\n            reply_version_id=reply_version_id or None,\n            tool_call_id=tool_call_id or None,')
replace('shenyu_gateway/tool_loop.py',
    'ctx.sessions.log_tool_result(ctx.session_id, _logged_tool_name(name, args), args, result)',
    'ctx.sessions.log_tool_result(\n            ctx.session_id, _logged_tool_name(name, args), args, result,\n            reply_version_id=str((ctx.meta.get("reply_archive_event") or {}).get("id")\n                                 or (ctx.log_entry or {}).get("reply_version_id") or ""),\n            tool_call_id=str(tool_call.get("id") or ""),\n        )', count=2)

# PWA: reversible organization, including an accessible restored-list path.
replace('pwa/src/api/client.ts',
    'fetchSessions(ctx: RequestContext, limit: number)',
    'fetchSessions(ctx: RequestContext, limit: number, visibility: "visible" | "hidden" | "all" = "visible")')
replace('pwa/src/api/client.ts', '/api/gateway/sessions?limit=${limit}',
        '/api/gateway/sessions?limit=${limit}&visibility=${visibility}')
replace('pwa/src/api/client.ts', 'export async function deleteSession(',
    '''export async function setSessionVisibility(ctx: RequestContext, sessionTag: string, hidden: boolean): Promise<void> {
  const response = await fetch(apiUrl(ctx, `/api/gateway/sessions/${encodeURIComponent(sessionTag)}/visibility`), {
    method: 'PATCH', headers: requestHeaders(ctx), body: JSON.stringify({ hidden }),
  })
  if (!response.ok) throw new Error(gatewayErrorMessage(response.status, await response.text()))
}

export async function deleteSession(''')
replace('pwa/src/App.vue', '  deleteSession,', '  setSessionVisibility,')
replace('pwa/src/App.vue', 'const recentSessions = ref<GatewaySession[]>([])',
    'const recentSessions = ref<GatewaySession[]>([])\nconst showHiddenSessions = ref(false)\nlet sessionListGeneration = 0\nwatch(showHiddenSessions, () => { void loadSessions() })')
section('pwa/src/App.vue', 'async function loadSessions() {', 'function sessionTitle(',
    '''async function loadSessions() {
  const generation = ++sessionListGeneration
  try {
    const payload = await fetchSessions(clientContext(), 100, showHiddenSessions.value ? 'hidden' : 'visible')
    if (generation !== sessionListGeneration) return
    recentSessions.value = Array.isArray(payload.sessions) ? payload.sessions : []
  } catch {
    // A network error is not an empty list and must not erase the last view.
  }
}

''')
section('pwa/src/App.vue', 'async function deleteSessionAction(', 'async function openSession(',
    '''async function setSessionHiddenAction(session: GatewaySession) {
  if (busy.value || !session.session_tag) return
  const hidden = !session.hidden_at
  try {
    await setSessionVisibility(clientContext(), session.session_tag, hidden)
    sessionActionTarget.value = null
    status.value = hidden ? '已收起对话，所有记录仍然保留' : '已放回最近对话'
    await loadSessions()
  } catch (error) {
    sessionActionError.value = error instanceof Error ? error.message : '列表状态没有更新，记录没有删除。'
  }
}

''')
replace('pwa/src/App.vue', '<div class="sidebar-section-title">Recents</div>',
    '<div class="sidebar-section-title">{{ showHiddenSessions ? "已收起" : "最近对话" }}</div>\n'
    '      <button class="sidebar-link" type="button" @click="showHiddenSessions = !showHiddenSessions">{{ showHiddenSessions ? "返回最近对话" : "查看已收起" }}</button>')
replace('pwa/src/App.vue', ':disabled="sessionActionTarget.session_tag === sessionTag"', ':disabled="busy"')
replace('pwa/src/App.vue', '@click="deleteSessionAction(sessionActionTarget)">删除</button>',
    '@click="setSessionHiddenAction(sessionActionTarget)">{{ sessionActionTarget.hidden_at ? "放回最近对话" : "收起对话" }}</button>')
replace('pwa/src/App.vue',
    '        <p v-else-if="sessionActionTarget.session_tag === sessionTag" class="settings-note">正在聊的这条不能删，换到别的对话再回来删它。</p>\n        <p v-else class="settings-note">删除只清网关里的快照和心跳，档案里我们说过的话都还在。</p>',
    '        <p v-else class="settings-note">只整理最近对话列表。心跳、聊天记录、工具过程、快照和照片都不会因此删除，可随时放回。</p>')
types = Path('pwa/src/types.ts').read_text()
marker = 'GatewaySession = {' if 'GatewaySession = {' in types else 'GatewaySession {'
replace('pwa/src/types.ts', marker, marker + '\n  hidden_at?: string | null')

# Admin uses the same safety contract instead of leaving a broken delete button.
replace('admin/src/api/sessions.ts', 'export interface GatewaySession {',
        'export interface GatewaySession {\n  hidden_at?: string | null')
section('admin/src/api/sessions.ts', 'export async function deleteGatewaySession(', 'export async function pruneGatewayRuntime(',
    '''export async function setGatewaySessionVisibility(sessionTag: string, hidden: boolean) {
  const { data } = await api.patch(`/api/gateway/sessions/${encodeURIComponent(sessionTag)}/visibility`, { hidden })
  return data
}

''')
replace('admin/src/views/SessionsView.vue', '  deleteGatewaySession,', '  setGatewaySessionVisibility,')
section('admin/src/views/SessionsView.vue', 'async function deleteSession(', 'async function dedupeMessages(',
    '''async function setSessionVisibility(sessionTag: string, hidden: boolean) {
  deletingTag.value = sessionTag
  try {
    await setGatewaySessionVisibility(sessionTag, hidden)
    message.success(hidden ? '已从 PWA 最近对话收起，记录全部保留' : '已放回 PWA 最近对话')
    await loadSessions()
  } catch (error) {
    message.error(errorText(error, '列表状态更新失败，记录没有删除'))
  } finally {
    deletingTag.value = ''
  }
}

''')
section('admin/src/views/SessionsView.vue',
    '            <NPopconfirm positive-text="删除" negative-text="取消" @positive-click="deleteSession(selectedSession.session_tag)">',
    '          </div>\n        </template>',
    '''            <NButton :loading="deletingTag === selectedSession.session_tag"
              @click="setSessionVisibility(selectedSession.session_tag, !selectedSession.hidden_at)">
              {{ selectedSession.hidden_at ? '放回 PWA 最近对话' : '从 PWA 最近对话收起' }}
            </NButton>
            <small>仅整理列表，不删除心跳、工具记录、快照或档案。</small>
''')

# No successful-looking lossy writes. Caller can expose false as unsaved state.
section('pwa/src/session/persistence.ts',
    '  // 落盘失败绝不打断 UI：配额爆时逐级降级',
    "  console.warn('persistStoredMessages: localStorage 配额不足，这一轮消息没有落盘')",
    '''  // A failed full write leaves the previous committed record untouched.
  // Rich process history is not disposable data: never trim outputs or erase events.
  try {
    localStorage.setItem(STORAGE_MESSAGES, JSON.stringify(windowRows))
    return true
  } catch {
    // The caller receives an explicit unsuccessful save, not a thinner success.
  }
''')
replace('pwa/src/session/persistence.ts',
    "  console.warn('persistStoredMessages: localStorage 配额不足，这一轮消息没有落盘')",
    "  console.warn('persistStoredMessages: 本机保存失败，上一份记录已保留')\n  return false")
replace('pwa/src/App.vue',
    '  persistStoredMessages(messages.value, sessionMessageLimit())',
    "  if (!persistStoredMessages(messages.value, sessionMessageLimit())) {\n    errorNotice.value = '本机保存没有成功，上一份记录仍在。请先保留当前页面。'\n  }")
# Delete now-unused lossy-only implementation rather than retain misleading dead code.
replace('pwa/src/session/persistence.ts', '// 配额告急时先把工具输出截到这个长度再重试落盘。\nconst EVENT_OUTPUT_PERSIST_LIMIT = 2000\n\n', '')
section('pwa/src/session/persistence.ts', 'function mapRowEvents(', '// 落盘是「从 UiMessage 重建一行」', '')
section('pwa/tests/persistence.spec.ts',
    "  it('truncates long event outputs when the first write overflows'",
    "  it('gives up quietly when storage keeps overflowing'",
    '''  it('reports quota failure without deleting tools or shortening their outputs', () => {
    const rejectedCount = withQuotaLimit(30000)
    const message = uiMessage('assistant', 'a', {
      events: [{ phase: 'tool_end', tool_call_id: 'c1', name: 'shenyu_recall', ok: true, output: 'x'.repeat(60000) }],
    })
    expect(persistStoredMessages([message], FALLBACK_SESSION_MESSAGE_LIMIT)).toBe(false)
    expect(rejectedCount()).toBe(1)
    expect(message.events[0].output).toHaveLength(60000)
    expect(loadStoredMessages()).toEqual([])
  })

  it('keeps the previous committed record when a larger write fails', () => {
    withQuotaLimit(30000)
    persistStoredMessages([uiMessage('user', 'already saved')], FALLBACK_SESSION_MESSAGE_LIMIT)
    const before = localStorage.getItem(STORAGE_MESSAGES)
    const message = uiMessage('assistant', 'new', {
      events: [{ phase: 'tool_end', tool_call_id: 'c1', name: 'shenyu_recall', ok: true, output: 'x'.repeat(60000) }],
    })
    expect(persistStoredMessages([message], FALLBACK_SESSION_MESSAGE_LIMIT)).toBe(false)
    expect(localStorage.getItem(STORAGE_MESSAGES)).toBe(before)
  })

''')
put('pwa/src/session/toolHydration.ts', Path('.github/pwa-retention/toolHydration.ts').read_text())
replace('pwa/tests/toolHydration.spec.ts',
    "it('matches from the tail so retry-duplicated assistant rows do not steal tools'",
    "it('does not guess tool ownership for ambiguous identity-less legacy replies'")
replace('pwa/tests/toolHydration.spec.ts',
    '    // 最后一条 UiMessage 先消费最后一个 assistant 行（带工具组）。\n    expect(messages[1].events).toHaveLength(2)',
    '    // Equal legacy text cannot prove which request owns a tool group.\n    expect(messages[1].events).toHaveLength(0)')

# Recovery supplements process receipts independently from visible-text changes.
replace('pwa/src/session/reconcile.ts',
    "import { hydrateToolEvents } from './toolHydration'",
    "import { hydrateToolEvents, mergeToolEvents, toolEventsFromRows } from './toolHydration'\nimport { stripStatusSuffix } from '../meta/statusSuffix'")
section('pwa/src/session/reconcile.ts',
    '  if (toolRows.length) {\n    const holder: UiMessage = {',
    '  return variant\n}',
    '''  variant.events = toolEventsFromRows(toolRows.filter(row => !row.reply_version_id
    || String(row.reply_version_id) === replyIdentity(variant)), String(reply.id || replyIdentity(variant) || 'recovery'))
''')
replace('pwa/src/session/reconcile.ts',
    'events: local.events.length ? local.events : incoming.events,',
    'events: mergeToolEvents(local.events, incoming.events),')
replace('pwa/src/session/reconcile.ts',
    '  let target = messages[lastUserIndex + 1]\n',
    '''  let target = messages[lastUserIndex + 1]
  // Validate the legacy user anchor BEFORE allocating a reply placeholder.
  // A known reply identity is stronger than any normalized visible text.
  if (!replyIdentity(target)) {
    const incomingUser = normalizeText(stripStatusSuffix(sessionMessageContent(payload.user_content)))
    const localUser = normalizeText(stripStatusSuffix(messages[lastUserIndex].content))
    if (!incomingUser || incomingUser !== localUser) return false
  }
''')
replace('pwa/src/session/reconcile.ts',
    '  if (contentChanged || mediaChanged) {',
    '''  const mergedEvents = mergeToolEvents(target.events, candidate.events)
  const eventsChanged = JSON.stringify(mergedEvents) !== JSON.stringify(target.events)
  if (eventsChanged) {
    target.events = mergedEvents
    variants[index].events = mergedEvents.map(event => ({ ...event }))
    changed = true
  }
  if (contentChanged || mediaChanged) {''')

# Stage-one docs: detailed behavior has one home, path map stays navigational.
replace('README.md',
    '- `pwa/src/session/toolHydration.ts`: rebuilds tool start/end events for snapshot-restored assistant rows from raw `tool` rows (tail-first, one group per assistant row, only when local events are empty).',
    '- `pwa/src/session/toolHydration.ts`: identity-bound tool receipt restoration and non-destructive missing-phase merge; ambiguous identity-less history is not guessed.')
replace('docs/architecture/REQUEST_CONTEXT.md',
    '### Transcript identity and recovery\n',
    '''### Transcript identity and recovery

Conversation-list organization uses `PATCH /api/gateway/sessions/{session_tag}/visibility` with a strict boolean `hidden`. It changes only `gateway_sessions.hidden_at`, never activity, cold-start eligibility, heartbeats, tools, snapshots, album media or archives. Session-list callers may request `visibility=visible|hidden|all`; existing internal readers default to all. PWA exposes both lists and restore. The legacy browser DELETE endpoint returns 409 without deleting anything, including calls from cached clients; the lower-level store deletion remains an explicit maintenance primitive, not a browser action.

New runtime tool receipts retain `reply_version_id` and the real `tool_call_id`. Hydration matches known reply identities and merges missing call phases without moving locally observed offsets or replacing completed results. Equal reply text does not suppress missing-tool recovery. Only unique identity-less legacy text can use fallback association; ambiguous groups remain unassigned. A failed legacy localStorage write preserves the prior committed value and reports failure; it never strips tool outputs/events to claim success.
''')
replace('docs/architecture/SYSTEM_ZONES.md',
    'session 删除仅覆盖带同一 `session_id` 的运行库数据，不删除独立聊天档案。',
    '浏览器会话列表只收起/恢复，不删除运行记录；旧 DELETE 入口拒绝执行。底层显式维护的 session 删除仍覆盖同一 `session_id` 的运行库数据，不删除独立聊天档案。')

# Fresh full verification; abort without committing product code on any failure.
for path in sorted(touched):
    if path.endswith('.py'):
        subprocess.run(['python', '-m', 'py_compile', path], check=True)
commands = [(['python','-m','pytest','tests/','-q'], None),
            (['npm','test'], 'pwa'), (['npm','run','build'], 'pwa'),
            (['npm','ci'], 'admin'), (['npm','test'], 'admin'), (['npm','run','build'], 'admin')]
failed = []
for command, cwd in commands:
    result = subprocess.run(command, cwd=cwd)
    if result.returncode: failed.append((command, result.returncode))
assert not failed, f'No product commit: verification failures {failed}'
subprocess.run(['git','diff','--check'],check=True)
subprocess.run(['git','diff','--stat'],check=True)
# Explicit allowlist only. Never stage the entire tree or force-push a ref.
subprocess.run(['git','add','--',*sorted(touched)],check=True)
subprocess.run(['git','config','user.name','shenyugateway repair workbench'],check=True)
subprocess.run(['git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com'],check=True)
subprocess.run(['git','commit','-m','fix(pwa): protect conversation records and restore missing tool receipts'],check=True)
subprocess.run(['git','push','origin','HEAD:refs/heads/'+BRANCH],check=True)
print('VERIFIED_PRODUCT_HEAD',subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),flush=True)
