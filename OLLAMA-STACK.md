# NoteDiscovery + Ollama + Open WebUI

A one-command local AI stack. Runs three services, downloads a small model, no cloud, no API keys.

| Service | URL | What it is |
|---|---|---|
| NoteDiscovery | http://localhost:8000 | Markdown notes app |
| Open WebUI | http://localhost:3000 | ChatGPT-style browser UI |
| Ollama | http://localhost:11434 | Local LLM runtime (OpenAI-compatible at `/v1`) |

Default model: `qwen2.5:1.5b` (~1 GB). Change it in `docker-compose.ollama-stack.yml` under `ollama-init`.

## Prerequisites

- Docker Desktop (Windows/macOS) or Docker Engine + Compose v2 (Linux)
- ~5 GB free disk, ~2 GB free RAM

## Start

From the repo root:

```bash
docker compose -f docker-compose.ollama-stack.yml up -d
docker compose -f docker-compose.ollama-stack.yml logs -f ollama-init   # wait for "Model ready."
```

First run pulls images + the model (5–10 min). After that it's seconds.

Then open:
- http://localhost:8000 — start taking notes (saved to `./data/`)
- http://localhost:3000 — pick `qwen2.5:1.5b` and chat

Quick sanity-check that Ollama is up:

```bash
curl http://localhost:11434/api/tags                                     # bash/zsh
Invoke-RestMethod http://localhost:11434/api/tags                        # PowerShell
```

## Connect Cursor

Two independent integrations. Enable either or both.

### Notes via MCP

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "notediscovery": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "NOTEDISCOVERY_URL=http://host.docker.internal:8000",
        "ghcr.io/gamosoft/notediscovery:latest",
        "python", "-m", "mcp_server"
      ]
    }
  }
}
```

Restart Cursor. Ask things like *"list my recent notes"* or *"create a note called scratch with today's date"*.

> Linux: `host.docker.internal` doesn't resolve by default. Add `"--add-host=host.docker.internal:host-gateway"` to the args array.

### Local model as Cursor's chat model

Cursor Settings → Models → add a custom OpenAI-compatible model:
- **Base URL:** `http://localhost:11434/v1`
- **API Key:** anything (e.g. `ollama`)
- **Model:** `qwen2.5:1.5b`

Only affects the chat model picker — Cursor Tab and background jobs still use Cursor's cloud models. If Cursor rejects the local URL (older versions validate from the cloud), expose it via `cloudflared tunnel --url http://localhost:11434` and use the tunnel URL instead.

## Useful commands

All commands below assume `COMPOSE_FILE=docker-compose.ollama-stack.yml` is set; otherwise prepend `-f docker-compose.ollama-stack.yml`.

```bash
docker compose logs -f <service>          # tail logs
docker compose exec ollama ollama list    # list installed models
docker compose exec ollama ollama pull qwen2.5-coder:3b   # add a model
docker compose down                       # stop (keeps everything)
docker compose down -v                    # stop + wipe models & chat history (notes survive)
docker compose pull && docker compose up -d   # update
```

Any model tag from https://ollama.com/library works. Rough RAM rule: 1B ≈ 1 GB, 3B ≈ 2 GB, 7B ≈ 5 GB.

## Data

- `./data/` — your notes (plain markdown, back this up)
- `ollama-models` volume — models (re-downloadable)
- `open-webui-data` volume — chat history (safe to wipe)

## Troubleshooting

- **Open WebUI shows "no models"** — model pull hasn't finished. Watch `docker compose logs -f ollama-init`.
- **Cursor MCP disconnected** — check `curl http://localhost:8000/health`, then restart Cursor.
- **Slow generation** — use a smaller model (`qwen2.5:0.5b`) or give Docker more CPU/RAM.
- **Port already in use** — edit the `ports:` mapping in `docker-compose.ollama-stack.yml`, then update your MCP config / URLs.

## Links

- NoteDiscovery: https://github.com/gamosoft/NoteDiscovery
- MCP tools reference: [`documentation/MCP.md`](documentation/MCP.md)
- Ollama library: https://ollama.com/library
