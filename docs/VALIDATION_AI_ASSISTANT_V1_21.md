# Validation — AI Assistant V1.21

## Required runtime checks

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase20_local_policy_and_validation
python manage.py test assistant.tests.test_phase6_refinement
python manage.py test assistant
python manage.py test
```

## Manual privacy check

1. Submit a filled `Create this client:` template containing a distinctive name,
   email, phone number, address, postal code, and internal note.
2. Confirm that the pending action preview contains the correct values.
3. Open the AI interaction record in the admin or inspect it through the shell.
4. Confirm that `prompt_summary` and `response_summary` contain only the fixed
   local-action metadata and none of the submitted customer values.
5. Confirm that disabling interaction-summary retention still stores the normal
   `[summary retention disabled]` marker.

## Manual usage-report check

1. Complete one free-form OpenAI assistant request.
2. Prepare one client through the zero-token structured template.
3. Open **AI Usage & Reliability**.
4. Confirm that:
   - Assistant interactions includes both records.
   - OpenAI requests includes only the provider-backed request.
   - Local actions includes only the structured-template request.
   - Token, cost, and average OpenAI latency exclude the local action.
5. Confirm that the current-month OpenAI request allowance did not increase for
   the local action.

## Safety assertions

- Local actions still require company/user access, structured-write permission,
  duplicate validation, and final confirmation.
- The action confirmation remains the execution source of truth.
- Provider-backed summaries and audit request IDs are unchanged.
- No database migration is required.
