# Wrapping the harness as an HTTP API

If you want to call ChatGPT Pro from other tools (curl, another agent, a Slack bot), wrap the harness in a small FastAPI server that exposes an OpenAI-compatible `/v1/chat/completions` endpoint.

## Minimal bridge

```python
# server.py
import asyncio, json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from lib.harness import ChatGPTSession

app = FastAPI()
# One long-lived session; reuse across requests for speed.
_session: ChatGPTSession | None = None

async def get_session() -> ChatGPTSession:
    global _session
    if _session is None:
        _session = ChatGPTSession(headless=True)
        await _session.__aenter__()
        await _session.ensure_pro()
    return _session

@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    # Collapse the messages array into the last user message
    # (the harness keeps multi-turn state inside one ChatGPT chat; for a
    #  stateless server you'd start a new chat per request — see below).
    prompt = "\n".join(m["content"] for m in body["messages"] if m["role"] == "user")
    s = await get_session()
    r = await s.ask(prompt, timeout=300)
    return JSONResponse({
        "id": "chatgpt-pro-bridge",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": r.text}}],
        "model": body.get("model", "chatgpt-pro"),
    })

# run: uvicorn server:app --port 8787
```

## Client

```bash
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is 2+2?"}]}'
```

Or point any OpenAI-compatible client at `OPENAI_BASE_URL=http://127.0.0.1:8787/v1` with any API key.

## Isolation strategy

ChatGPT keeps conversation context within one chat. For a multi-tenant or stateless server, start a new chat per request so prompts don't bleed:

```python
r = await s.ask(prompt)      # continues the same chat
# vs
await s.new_chat()           # isolated
r = await s.ask(prompt)
```

For a single-user local tool, reusing one chat is faster but accumulates context (higher token usage, slower responses). `new_chat()` every N requests is a good balance.

## Streaming

True SSE streaming (token-by-token) requires intercepting ChatGPT's internal event stream, which is fragile. For most use cases, the harness's "wait for completion, return full text" is fine — the perceived latency is similar because ChatGPT streams fast. If you need real streaming, the approach is to poll the assistant turn's `innerText` every 100-200ms and emit deltas; see `run_suite.py`'s `_wait_turn_done` for the polling pattern.

## Reference: `glm-pool`

The user's existing `~/ZCodeProject/glm-pool/server.py` is a 2000-line FastAPI proxy with OpenAI + Anthropic endpoint mapping, account pooling, and rate-limit handling. Its *structure* (single file, 127.0.0.1, no DB) is the right template — but it talks to OpenCode Go's HTTP API, not the browser. To build a ChatGPT Pro bridge, copy its skeleton and replace the upstream call with `s.ask()`.

## Safety notes

- Bind to `127.0.0.1` only. Do not expose the bridge to the network — it would let anyone call your ChatGPT account.
- No auth is fine for local use; add a token check if you must expose it.
- The bridge inherits the ToS caveat: automating the ChatGPT web UI is against OpenAI's terms. Personal/research use.
