import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import McpServersCard from './McpServersCard.vue'

const fetchMcpServers = vi.fn()
const saveMcpServers = vi.fn()
const testMcpServer = vi.fn()
const refreshMcpTools = vi.fn()

vi.mock('@/api/mcp', async () => {
  const actual = await vi.importActual<typeof import('@/api/mcp')>('@/api/mcp')
  return {
    ...actual,
    fetchMcpServers: (...args: unknown[]) => fetchMcpServers(...args),
    saveMcpServers: (...args: unknown[]) => saveMcpServers(...args),
    testMcpServer: (...args: unknown[]) => testMcpServer(...args),
    refreshMcpTools: (...args: unknown[]) => refreshMcpTools(...args),
  }
})

const everything = {
  name: 'everything',
  url: 'http://127.0.0.1:3001/mcp',
  transport: 'auto' as const,
  headers: { Authorization: 'Bear****oken' },
  enabled: true,
}

const listResponse = {
  servers: [everything],
  status: [{
    name: 'everything',
    url: everything.url,
    transport: 'auto',
    ok: true,
    error: null,
    tool_count: 8,
    checked_at: '2026-08-13T04:00:00+00:00',
  }],
  tools: [{
    name: 'mcp_everything_echo',
    server: 'everything',
    remote_name: 'echo',
    description: 'Echoes back whatever you send.',
  }],
}

async function mountCard() {
  const wrapper = mount(McpServersCard)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  fetchMcpServers.mockResolvedValue(listResponse)
  saveMcpServers.mockImplementation(async (servers) => ({ ok: true, servers }))
})

describe('McpServersCard list rendering', () => {
  it('shows server row with status, tool count, and merged tool names', async () => {
    const wrapper = await mountCard()
    const row = wrapper.get('[data-testid="mcp-server-row-everything"]')
    expect(row.text()).toContain('everything')
    expect(row.text()).toContain('http://127.0.0.1:3001/mcp')
    expect(row.text()).toContain('工具 8 个')
    expect(row.find('.mcp-status-dot').classes()).toContain('ok')
    expect(wrapper.get('[data-testid="mcp-tools"]').text()).toContain('mcp_everything_echo')
  })

  it('shows the empty hint when no servers are configured', async () => {
    fetchMcpServers.mockResolvedValue({ servers: [], status: [], tools: [] })
    const wrapper = await mountCard()
    expect(wrapper.find('[data-testid="mcp-empty"]').exists()).toBe(true)
  })

  it('marks a failing server with the error dot and its message', async () => {
    fetchMcpServers.mockResolvedValue({
      servers: [{ ...everything, name: 'broken', url: 'http://bad.example/mcp' }],
      status: [{
        name: 'broken',
        url: 'http://bad.example/mcp',
        transport: 'auto',
        ok: false,
        error: 'ConnectError: refused',
        tool_count: 0,
        checked_at: '2026-08-13T04:00:00+00:00',
      }],
      tools: [],
    })
    const wrapper = await mountCard()
    const row = wrapper.get('[data-testid="mcp-server-row-broken"]')
    expect(row.find('.mcp-status-dot').classes()).toContain('error')
    expect(row.text()).toContain('ConnectError: refused')
  })
})

describe('McpServersCard form validation', () => {
  it('blocks invalid names before any network call', async () => {
    const wrapper = await mountCard()
    await wrapper.get('[data-testid="mcp-add-server"]').trigger('click')
    await wrapper.get('[data-testid="mcp-form-name"] input').setValue('Bad Name')
    await wrapper.get('[data-testid="mcp-form-url"] input').setValue('http://ok.example/mcp')
    await wrapper.get('[data-testid="mcp-form-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="mcp-form-error"]').text()).toContain('名称')
    expect(saveMcpServers).not.toHaveBeenCalled()
  })

  it('blocks non-http URLs before any network call', async () => {
    const wrapper = await mountCard()
    await wrapper.get('[data-testid="mcp-add-server"]').trigger('click')
    await wrapper.get('[data-testid="mcp-form-name"] input').setValue('fresh')
    await wrapper.get('[data-testid="mcp-form-url"] input').setValue('ws://nope')
    await wrapper.get('[data-testid="mcp-form-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="mcp-form-error"]').text()).toContain('URL')
    expect(saveMcpServers).not.toHaveBeenCalled()
  })

  it('saves a valid new server through the API', async () => {
    const wrapper = await mountCard()
    await wrapper.get('[data-testid="mcp-add-server"]').trigger('click')
    await wrapper.get('[data-testid="mcp-form-name"] input').setValue('fresh')
    await wrapper.get('[data-testid="mcp-form-url"] input').setValue('http://ok.example/mcp')
    await wrapper.get('[data-testid="mcp-form-save"]').trigger('click')
    await flushPromises()
    expect(saveMcpServers).toHaveBeenCalledTimes(1)
    const sent = saveMcpServers.mock.calls[0][0]
    expect(sent).toHaveLength(2)
    expect(sent[1]).toMatchObject({ name: 'fresh', url: 'http://ok.example/mcp', transport: 'auto', enabled: true })
  })
})

describe('McpServersCard masked headers', () => {
  it('edit form shows the masked value, never the original secret', async () => {
    const wrapper = await mountCard()
    await wrapper.get('[data-testid="mcp-edit-everything"]').trigger('click')
    const headerValue = wrapper.get('[data-testid="mcp-header-value-0"] input')
    expect((headerValue.element as HTMLInputElement).value).toBe('Bear****oken')
  })

  it('re-saving without touching the header sends the masked placeholder back untouched', async () => {
    const wrapper = await mountCard()
    await wrapper.get('[data-testid="mcp-edit-everything"]').trigger('click')
    await wrapper.get('[data-testid="mcp-form-save"]').trigger('click')
    await flushPromises()
    expect(saveMcpServers).toHaveBeenCalledTimes(1)
    const sent = saveMcpServers.mock.calls[0][0]
    // The backend replaces masked values with the stored secret; the UI must
    // not invent or reveal the original.
    expect(sent[0].headers).toEqual({ Authorization: 'Bear****oken' })
  })
})
