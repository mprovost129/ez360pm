# EZ360PM AI Assistant V1.18

## Focused action fast path

This release responds to live client-creation testing where the assistant used too
many tokens or spent too long deciding what to do.

### Changes

- A complete natural-language create-client request now forces the one exposed
  `create_client` function through OpenAI's Responses API tool choice.
- An incomplete request such as "Create a client" is not forced; the assistant can
  ask one concise question for the required contact name.
- Focused write requests no longer include earlier conversation summaries.
- Focused client creation no longer includes unrelated current-page context.
- Focused writes are limited to one provider round and one registered tool call.
- Focused requests use compact system instructions, a 600-token default output cap,
  minimal reasoning effort, and low text verbosity.
- The ordinary multi-tool assistant path retains its existing limits and behavior.

### Safety

The change does not bypass confirmation, company scoping, duplicate detection,
strict tool schemas, explicit write intent, stale-data checks, or idempotency.
Client creation is still only prepared until the user confirms the action card.

### Configuration

```env
AI_FOCUSED_MAX_OUTPUT_TOKENS=600
AI_FOCUSED_REASONING_EFFORT=minimal
AI_FOCUSED_VERBOSITY=low
```

No database migration is required.
