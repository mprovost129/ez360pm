# EZ360PM AI Assistant V1.31

## True lazy AI provisioning and disabled-mode signal isolation

Company and user creation no longer writes to assistant-owned tables. This is true
whether the platform AI flag is disabled or enabled.

- `AICompanySettings` is created only when the AI settings screen is saved or an
  assistant workflow explicitly requests the company policy.
- `AIUserAccess` is created only when staff explicitly grant or revoke selected-user
  pilot access.
- Creating an ordinary Company or User does not create assistant policy or access
  records.
- When `AI_ASSISTANT_ENABLED=false`, document, line-item, credit, delivery, and
  deletion signals skip AI draft-quality tracking before any assistant-table query
  is scheduled.
- Existing policy, access, interaction, action, and draft-review records are retained.

This aligns the implementation with the optional-AI boundary introduced in V1.29
and V1.30. Ordinary CRM, project, document, and billing workflows remain database-
neutral with respect to the assistant when the feature is disabled.

No database migration or static-file collection is required.
