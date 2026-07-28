# EZ360PM AI Assistant V1.17 Release Notes

## Purpose

V1.17 is a real-use correction prompted by client-creation testing. It makes
single-action commands faster and more predictable without adding new AI
capabilities or authority.

## Focused tool routing

When the current message clearly requests one ordinary action—such as creating a
client, updating a project, adding a contact, creating a note, or controlling the
timer—the server sends OpenAI only the relevant registered tool instead of the
entire assistant catalog.

This reduces:

- tool-schema input tokens;
- incorrect exploratory searches;
- unrelated tool selection;
- latency and timeout exposure;
- the chance that a simple request expands into several actions.

Ambiguous and genuinely multi-part requests retain the normal catalog so the
assistant can ask a question or select an appropriate combined workflow.

## Immediate stop after preparation

A write action is still only prepared until the user confirms it. Once a pending
confirmation has been created, the server now returns a deterministic review
message immediately. It does not make another OpenAI call merely to restate that
the confirmation is ready.

This applies to every write-risk level and preserves all existing confirmation,
idempotency, stale-data, company-scope, and financial-safety controls.

## Tool-call budget

`AI_MAX_TOOL_CALLS` places a hard per-request ceiling on registered tool calls.
The default is four. Focused single-action requests use a stricter one-call
budget. Requests that exceed the budget fail safely and ask the user to split the
work into a shorter command.

## Intent corrections

Write-intent patterns were tightened so phrases such as “change the project
address” do not accidentally authorize the project-status workflow, and “add a
note to a client” does not look like a request to create a new client.

## Configuration

```env
AI_MAX_TOOL_CALLS=4
```

No database migration is required.
