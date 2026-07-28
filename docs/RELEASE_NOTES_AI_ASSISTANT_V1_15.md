# EZ360PM AI Assistant V1.15 Release Notes

## AI workflow completion and usability

V1.15 closes the remaining code-side usability gaps identified before real-world
pilot testing. It does not add scheduled or autonomous behavior.

### Bounded multi-turn context

- The browser maintains a random conversation identifier in session storage.
- EZ360PM can reuse up to the configured number of recent, redacted interaction
  summaries from the same authenticated user, company, and conversation.
- Context expires after a configurable idle window.
- A **New conversation** control clears the visible transcript and starts a new
  identifier.
- Earlier turns never authorize a write. Explicit write intent must still appear
  in the current user message.
- Disabling redacted summary retention also disables server-side multi-turn
  context automatically.

### Server-verified current-page context

- The assistant can understand references such as “this project,” “this client,”
  “this proposal,” or “this invoice” from supported authenticated pages.
- The browser sends only its current path.
- Django resolves the route and re-queries the referenced record through
  `request.user.company` before any context reaches OpenAI.
- Unsupported, missing, or cross-company paths provide no page context.
- Only minimal identifiers and labels are supplied; notes, descriptions, public
  tokens, payment references, and other sensitive free text are excluded.

### Persistent AI Action Center

- Pending confirmations can be recovered after closing the assistant or changing
  pages.
- The Action Center lists current pending actions and recent outcomes for the
  authenticated user only.
- Expired confirmations are closed automatically.
- External and financial commits retain the final-review acknowledgement.
- The assistant drawer also reloads pending actions and shows their count.
- Starting a new conversation does not discard pending actions; they remain in
  the Action Center until confirmed, canceled, or expired.

### Configuration

```env
AI_CONVERSATION_CONTEXT_TURNS=4
AI_CONVERSATION_CONTEXT_MINUTES=60
```

Set context turns to `0` to disable multi-turn context while keeping the
assistant available.

### Migration

```text
assistant.0009_ai_conversation_and_page_context
```

### Safety boundary retained

V1.15 does not add scheduled drafts, repeating reminders, batch sending,
autonomous sending, refunds, paid-invoice alteration, deletion of financial
history, or money movement.
