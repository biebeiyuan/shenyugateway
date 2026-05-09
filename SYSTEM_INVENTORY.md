# Shenyu Gateway System Inventory

## Scope

This folder is the current chat gateway project:

- Root: `C:\Users\曾\Desktop\shenyu-gateway`
- Main backend entry: `gateway.py`
- Active admin UI: `admin/src/`
- Local runtime config: `.env`
- Local runtime data: `data/shenyu_gateway.db`

## What Belongs To This Project

### Core application

- `gateway.py`
  - FastAPI app
  - upstream proxy
  - config API
  - session/cache store integration
  - context injection
  - gateway-native tools

- `admin/src/`
  - active Vue admin source for `/admin`
  - configuration, sessions, logs, calendar, and Mem0 pages

- `.env` / `.env.example`
  - runtime configuration

- `data/shenyu_gateway.db`
  - local SQLite work layer
  - sessions, context snapshots, raw request windows, caches, heartbeats

- `README.md`
  - architecture and operating notes

### Local-but-generated artifacts

- `__pycache__/`
- `admin/node_modules/`
- `admin/dist/`

These should not be treated as source of truth.

## What Does Not Belong To This Project

The sibling folder below is reference material only and is not part of the current gateway runtime:

- `C:\Users\曾\Desktop\shenyu`

Known items there:

- `briefingmain.py`
  - early MCP/briefing prototype
  - not imported by the current gateway

- `mcpserver.py`
  - separate MCP server prototype/reference
  - not imported by the current gateway

- `browserserver.py`
  - separate browser MCP prototype/reference
  - not imported by the current gateway

- `gateway_architecture.md`
  - reference design notes

- `网关1.txt` / `网关2.txt` / `网关3.txt` / `本人supabase.txt`
  - notes only

## External Dependencies Outside This Folder

These still affect behavior even though they are not source files in this folder:

- Supabase tables and RPC functions
  - memory and briefing behavior depend on them

- Upstream provider configuration in `.env`

- Client request headers
  - especially session tags such as `X-Shenyu-Session-Tag`

## Current Source Of Truth

If future edits change the gateway behavior, start in this folder unless the change is specifically about:

- Supabase schema or RPCs
- the separate MCP prototypes in `Desktop\shenyu`
- the chat client configuration itself
