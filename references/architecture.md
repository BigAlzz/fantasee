# Subprocess Streaming Architecture

A reusable pattern for spawning long-running work as a subprocess and streaming live progress to a web frontend via WebSocket.

## The Pattern

```
User clicks "Generate" in browser
        │
        ▼
  FastAPI endpoint (POST /api/generate)
        │
        ├── Creates task record with status="queued"
        ├── Notifies WebSocket clients
        ├── Spawns asyncio.create_task(_run_pipeline(task_id))
        └── Returns {task_id} immediately
                 │
                 ▼
        asyncio.create_subprocess_exec(...)
                 │
          ┌──────┴──────┐
          │              │
     read_stdout()   read_stderr()
          │              │
    Parse markers     Collect errors
   ┌──────────┐
   │          │
__PROGRESS__:   __RESULT__:
  {"status":     {"id":"...",
   "message":     "title":"...",
   "progress":    "scene_count":...
   0.5}           "status":"complete"}
   │                  │
   ▼                  ▼
Update task      Update task + reload
record + push    story cache + push
via WebSocket    final WS event
```

## Key Components

### 1. Progress Markers (on subprocess stdout)

The child process emits structured JSON on dedicated marker lines:

```
__PROGRESS__:{"status":"running","message":"Generating scene 3...","progress":0.35}
__RESULT__:{"id":"story-abc","title":"My Story","status":"complete"}
```

Normal stdout/stderr output should be avoided — the backend only reads these lines.

### 2. Backend (FastAPI)

```python
async def _run_pipeline(task_id, request):
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "API_KEY": os.environ.get("API_KEY", "")},  # ← critical!
    )

    async def read_stdout():
        while True:
            line = await process.stdout.readline()
            if not line: break
            text = line.decode().strip()
            if text.startswith("__PROGRESS__:"):
                data = json.loads(text[13:])
                update_task(task_id, data)
                await broadcast_to_websockets(task_id, data)

    async def read_stderr():
        ... # collect errors

    await asyncio.gather(read_stdout(), read_stderr())
    await process.wait()
```

### 3. Frontend

```javascript
// Connect to WebSocket
const ws = new WebSocket(`ws://${host}/ws`);
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'task_update' && data.task_id === currentTaskId) {
        updateProgressBar(data.progress);
        showStatus(data.message);
        if (data.status === 'done') refreshStories();
    }
};

// Submit generation
async function generate(params) {
    const resp = await fetch('/api/generate', {
        method: 'POST',
        body: JSON.stringify(params),
    });
    const { task_id } = await resp.json();
    pollOrWaitForWebSocket(task_id);
}
```

## Critical: Credential Passing (Hermes-specific)

**Hermes masks API keys in static config files.** Both `config.yaml` and `.env` store the actual key value as `***` after Hermes writes them. A subprocess that reads those files directly will get the masked value and fail with 401/403.

**The fix:** Always pass credentials explicitly through the subprocess environment:

```python
env={**os.environ, "MY_API_KEY": os.environ.get("MY_API_KEY", "")}
```

The parent process (Hermes agent / server) has the real key in its environment — the child inherits it.

## Variants

- **Polling fallback**: If WebSocket isn't available, the frontend can poll `GET /api/generate/tasks/{task_id}` every 2 seconds.
- **ComfyUI image gen**: The same pattern works for image rendering — emit progress between each scene, gracefully skip if ComfyUI is unreachable.
- **Multiple concurrent tasks**: Use a dict keyed by `task_id` to track state; the WebSocket handler sends updates for all active tasks.
