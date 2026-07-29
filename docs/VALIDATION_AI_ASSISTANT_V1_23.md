# V1.23 validation — local template and provider setup safety

## Automated checks

Run:

```bash
python manage.py test assistant.tests.test_phase23_local_validation_and_provider_setup
python manage.py test assistant.tests.test_phase19_retry_and_local_fast_path
python manage.py test assistant.tests.test_phase20_local_policy_and_validation
python manage.py evaluate_ai_assistant
python manage.py test assistant
```

## Manual checks

### Incomplete local template

1. Open the assistant and select **Client template**.
2. Fill `Contact first name` but leave `Contact last name` blank.
3. Submit.
4. Confirm that EZ360PM identifies the missing field immediately.
5. Confirm that no pending action is created.
6. Confirm in AI Usage & Reliability that the interaction is local, has zero
   tokens and zero cost, and is classified as needs correction.
7. Confirm that the retained summaries do not contain the submitted name,
   address, email, phone, or note values.

### Complete local template

1. Complete both required contact-name fields.
2. Submit and confirm the normal review card appears.
3. Confirm the client is not created until final confirmation.
4. Confirm duplicate email/phone validation still runs.

### Provider configuration failure

1. In a non-production environment, temporarily remove `OPENAI_API_KEY`.
2. Submit a read-only free-form question.
3. Confirm the assistant returns a safe configuration message instead of a 500.
4. Confirm no action is prepared and the failed interaction is visible in the
   AI reliability report.
5. Restore the key and rerun the OpenAI connection test.

### Invalid model selection

1. Set a company model override that is not present in `AI_ALLOWED_MODELS`.
2. Submit a provider-backed request.
3. Confirm the request is blocked with an allowlist/settings message before an
   OpenAI call is made.
4. Restore an approved model and rerun the readiness check.
