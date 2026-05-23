---
name: local-subagent-story-generation
description: "Delegate story/script generation to local LM Studio subagents while main agent stays on fast cloud model. Prevents machine freezing by keeping local model context tiny."
version: 1.0.0
author: Hermes Agent
tags: [story, writing, local-llm, delegation, performance]
---

# Local Subagent Story Generation

## Problem

Running Hermes with a local LM Studio model causes full machine freezing during generation because Hermes sends massive context (16k+ tokens — system prompt, tools, memory, conversation history) to the local model. The local model's GPU load pegs the system.

## Solution: Split Architecture

- **Main agent** runs on a fast cloud model (DeepSeek, OpenRouter, etc.) — responsive, never freezes
- **Subagents** run on local LM Studio (`custom:lmstudio` provider) with MINIMAL context (300-500 tokens)
- Subagents only receive the specific task + essential background, not the full conversation

## Prerequisites

1. `custom:lmstudio` provider configured in Hermes config (base_url pointing to LM Studio server)
2. `delegation.provider` set to `custom:lmstudio`
3. `delegation.model` set to a lightweight local model (e.g., `gemma-4-e2b-it` at 2B params)

### CRITICAL: Verify delegation config before delegating

Subagents **inherit the parent's provider/transport** unless delegation settings are explicitly configured. If `delegation.provider` is not set to `custom:lmstudio`, your subagent will silently run on your cloud model (DeepSeek, Anthropic, etc.) — defeating the purpose and burning API credits.

Before delegating, verify:

```bash
hermes config get delegation.provider
hermes config get delegation.model
```

Expected output for local generation:
```
custom:lmstudio
<model-name>  (e.g. gemma-4-e2b-it, qwen3-4b-thinking-2507)
```

If these return empty or show a cloud provider, set them:
```bash
hermes config set delegation.provider custom:lmstudio
hermes config set delegation.model <local-model-name>
```

## How to Delegate

### Basic Pattern

```python
# Main agent (on cloud model) delegates to local subagent
result = delegate_task(
    goal="Write 3 paragraphs of dialog for scene where the protagonist discovers the hidden laboratory",
    context="""Story: "The Last Rampart"
Setting: Post-apocalyptic underground bunker, year 2187
Protagonist: Dr. Elara Voss, 42, chief engineer
Current scene: Scene 4 — Discovery
Previous: Elara found a sealed door behind the reactor core
Tone: Tense, atmospheric, with moments of wonder
Style: Third person limited, present tense""",
    toolsets=["terminal", "file"]
)
```

### Key Rules

1. **Keep context tiny** — 300-500 tokens max. Only the bare essentials: character names, setting, scene number, tone/style. Do NOT include the full story so far.

2. **One scene at a time** — Delegate individual scenes, not entire stories. A subagent with 500 tokens of context runs in seconds. A subagent with 4000 tokens will freeze the machine again.

3. **Chain results** — After each subagent returns, add their output to your context and pass the updated summary to the next subagent.

4. **Use toolsets=['terminal', 'file']** — The subagent only needs terminal (to call LM Studio via API) and file access. Don't give it web/browser/vision tools — that's wasted context.

> **Context template**: See `templates/minimal-story-context.txt` for a pre-packaged minimal context format. Copy-paste and fill in your values.

### Example Workflow

```
Main agent (DeepSeek)          Subagent 1 (LM Studio)     Subagent 2 (LM Studio)
      │                              │                          │
      ├── delegate(scene 4) ────────►│                          │
      │                              ├── writes scene 4         │
      │◄───────── summary ──────────┤                          │
      │                                                         │
      ├── delegate(scene 5) ──────────────────────────────────►│
      │                                                         ├── writes scene 5
      │◄────────────────── summary ────────────────────────────┤
      │                                                         │
      └── compile & deliver ✅
```

## Pitfalls

- **Silent cloud model fallback (CRITICAL)**: If `delegation.provider` is not set or points to a cloud model, `delegate_task` subagents inherit the parent's provider by default. The subagent will happily use DeepSeek/Anthropic/OpenAI instead of your local LM Studio — no error, no warning. Always check `delegation.provider` (see Prerequisites above) before delegating, and verify the `model` field in the subagent's result after.
- **Synchronous wait**: `delegate_task` is synchronous. The main agent is blocked while the subagent runs. For a 300-token story generation task on a 2B model, this is ~10-30 seconds — acceptable.
- **GPU still pegs**: The local model still uses the GPU. But with tiny context (300 vs 16000 tokens), it finishes in seconds instead of minutes, so the freeze is brief.
- **Don't include full chat history**: The subagent has no memory of your conversation. Pass only what's needed via the `context` field.
- **DeepSeek context limits**: DeepSeek has ~131k context. Accumulating all subagent outputs is fine.
- **Subagent can't clarify**: Leaf subagents cannot use `clarify` tool. Make your goal self-contained and unambiguous.

## Verification

After delegating, verify the subagent used the correct model AND returned content:

1. **Check `model` field** — the result object contains `model`. If it shows a cloud model (e.g., `deepseek-v4-flash`, `claude-sonnet-4`) instead of your local model, the delegation provider wasn't set correctly. Example result object:
   ```json
   {
     "status": "completed",
     "summary": "...",
     "model": "deepseek-v4-flash"    // ← WRONG — should be your local model
   }
   ```

2. **Check content is non-empty** — verify the `summary` isn't empty or error-like.

3. **If writing to a file** — confirm the file exists with `read_file()`.
