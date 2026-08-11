# Local AI assistant plan

## Goal

The server owner can optionally install a local model. The model serves the
whole local team through the Task Manager server; no cloud API key is required.

## Delivery stages

1. **Optional local runtime** — the administrator panel detects a local Ollama
   instance and lists downloaded models. Nothing is installed automatically.
2. **Text chat** — authenticated users open the Assistant page. Chat history is
   scoped to the user and their group.
3. **Safe actions** — the assistant returns a proposed action, such as creating
   a task or reminder. The server executes it only after an explicit user
   confirmation.
4. **Permissions** — every proposed action is checked against the same group
   role rules as the standard interface.
5. **Voice** — browser speech input and speech output use the same chat/action
   flow. Speech is optional and never bypasses confirmation.

## Security boundaries

- Only the server administrator can see local-model status or configure it.
- The model receives only the minimum task and group context necessary for a
  request.
- API keys are not needed for the local runtime and are never sent to clients.
- A model response is treated as untrusted text; it cannot execute an action
  directly.
