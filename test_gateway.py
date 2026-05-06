"""快速测试网关"""
import httpx, json, os

# 不走代理，直连 localhost
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("ALL_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("all_proxy", None)

client = httpx.Client(proxy=None, timeout=120.0)

print("=== 1. 测试 /health ===")
r = client.get("http://localhost:8000/health")
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

print("\n=== 2. 测试 /v1/chat/completions ===")
body = {
    "model": "claude-sonnet-4-20250514",
    "messages": [{"role": "user", "content": "hi"}],
    "stream": False,
}
r = client.post("http://localhost:8000/v1/chat/completions", json=body)
print(f"Status: {r.status_code}")
print(f"Response: {r.text[:1000]}")
