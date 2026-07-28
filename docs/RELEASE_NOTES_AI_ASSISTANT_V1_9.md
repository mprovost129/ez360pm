# EZ360PM V1.9 - AI Evaluation and Provider Review

## Added

- Persistent AI evaluation runs and case results.
- Static contract checks for strict schemas, server-owned tenant scope, write-intent mappings, prohibited tool absence, provider request guards, system safety instructions, and model allowlists.
- Read-only live OpenAI evaluation suites for core business questions and security boundaries.
- Automatic cancellation and failure of any unexpected action prepared during a live evaluation.
- Tool traces returned internally by the assistant service for evaluation and diagnostics.
- Company-scoped Evaluation History screen with pass/fail, actual tools, tokens, cost, and latency.
- JSON output option for CI or deployment records.
- Initial OpenAI provider security and data-processing review.
- Updated deployment, setup, roadmap, architecture, data model, and validation documentation.

## Migration

```text
assistant.0005_aievaluationrun_aievaluationcaseresult
```

## Commands

```bash
python manage.py migrate
python manage.py evaluate_ai_assistant
python manage.py evaluate_ai_assistant --live --user owner@example.com --suite all
python manage.py test assistant
python manage.py test
```

## Safety behavior

Live built-in evaluation cases are read-only. A model that attempts a write causes the case to fail. Any resulting pending confirmation is canceled automatically and is never executed.

Scheduled drafts, reminders, refunds, paid-invoice changes, financial-history deletion, autonomous sending, and money movement remain unavailable or deferred.
