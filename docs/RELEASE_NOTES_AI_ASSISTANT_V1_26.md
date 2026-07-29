# EZ360PM AI Assistant V1.26

## Local client-template routing correction

V1.26 fixes a routing defect between the server-rendered client template and the
explicit-write-intent matcher.

The drawer renders the human-readable prefix and labels:

```text
Create this client:
Contact first name:
Contact last name:
```

Before this release, the intent matcher accepted `create client` and underscore
labels such as `contact_first_name`, but did not reliably accept the exact
`Create this client:` wording with spaced labels. Because deterministic local
actions are selected only after the server approves the matching write intent, a
filled drawer template could fall through to the OpenAI path even though the local
parser itself understood it.

V1.26 now:

- recognizes `Create this client:` as an explicit current-turn create-client request;
- accepts both spaced template labels and underscore-style labels;
- routes complete templates to the focused deterministic `create_client` workflow;
- routes incomplete templates to the local required-field correction workflow;
- preserves confirmation, duplicate detection, company scoping, privacy, and local
  rate limits;
- adds an integration-level routing regression test using the actual shared template.

No AI authority was added and no database migration is required.
