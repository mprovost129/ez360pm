# EZ360PM AI Assistant V1.27

## Local client-template precedence and payload isolation

V1.27 closes an edge case in the zero-token client workflow.

The local client template can contain ordinary client notes such as:

```text
Internal note: Send the invoice next week and start the timer after approval.
```

Before this release, the broad write-intent matcher could interpret those words as
additional assistant commands. That could cause the request to lose its focused
local route and expose the template to the broader OpenAI tool catalog.

V1.27 now treats the explicit `Create this client:` prefix as a server-owned routing
boundary:

- the request always selects only the deterministic `create_client` workflow;
- values in every later template field are treated as client data, not commands;
- complete templates still produce the normal local confirmation preview;
- incomplete templates still return a local required-field correction;
- OpenAI is not called and no provider request allowance is consumed;
- duplicate detection, company scoping, privacy protections, rate limits, and final
  confirmation remain unchanged.

No AI authority was added and no database migration is required.
