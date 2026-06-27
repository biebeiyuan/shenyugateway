import { api } from './http'

export interface RoomTrace {
  id: string
  session_id: string
  action: string
  detail: any
  scribble: string | null
  created_at: string
}

export interface DrawerNote {
  id: string
  content: string
  read_at: string | null
  created_at: string
}

export interface RoomScribble {
  id: string
  content: string
  created_at: string
}

export interface RoomPin {
  id: string
  content: string
  done: boolean
  created_at: string
}

export interface RoomTool {
  type: string
  function: {
    name: string
    description?: string
    parameters?: Record<string, unknown>
  }
}

export async function fetchRoomTraces(limit = 30) {
  const { data } = await api.get('/api/gateway/room/traces', { params: { limit } })
  return data as { traces: RoomTrace[]; count: number }
}

export async function fetchRoomPreview() {
  const { data } = await api.get('/api/gateway/context/preview/room')
  return data as { charge: number; layers: Record<string, string>; mode: string; room_tools?: RoomTool[] }
}

export async function fetchDrawerNotes(limit = 20) {
  const { data } = await api.get('/api/gateway/room/drawer-notes', { params: { limit } })
  return data as { notes: DrawerNote[]; count: number; unread: number }
}

export async function createDrawerNote(content: string) {
  const { data } = await api.post('/api/gateway/room/drawer-notes', { content })
  return data as { ok: boolean; id: string }
}

export async function markDrawerNotesRead(ids: string[]) {
  const { data } = await api.post('/api/gateway/room/drawer-notes/read', { ids })
  return data as { ok: boolean; marked: number }
}

export async function fetchScribbles(limit = 20) {
  const { data } = await api.get('/api/gateway/room/scribbles', { params: { limit } })
  return data as { scribbles: RoomScribble[]; count: number }
}

export async function fetchPins(include_done = false) {
  const { data } = await api.get('/api/gateway/room/pins', { params: { include_done } })
  return data as { pins: RoomPin[]; count: number }
}
