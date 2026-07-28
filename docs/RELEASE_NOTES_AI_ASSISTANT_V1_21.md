# EZ360PM V1.21 — Local-action privacy and accurate usage reporting

## Purpose

V1.21 closes two practical gaps in the zero-token client-template workflow:
customer fields were still copied into retained AI interaction summaries, and the
Usage & Reliability screen mixed local deterministic actions with OpenAI-backed
requests when reporting request volume and latency.

## Changes

### Local-action summary privacy

- A deterministic `Create this client:` submission now stores a fixed metadata
  summary instead of a redacted copy of the submitted template.
- Names, company/household names, billing addresses, email addresses, phone
  numbers, postal codes, and internal notes are omitted from both the stored
  prompt summary and stored outcome summary for the local path.
- The pending confirmation still carries the fields required for review and
  execution. This change only removes unnecessary duplication in
  `AIInteraction` history.
- Provider-backed OpenAI requests continue using the existing redacted-summary
  behavior when summary retention is enabled.

### Usage and reliability reporting

- The report now distinguishes:
  - all assistant interactions;
  - OpenAI-backed requests;
  - zero-token local actions.
- Token totals, estimated API cost, and average OpenAI latency are calculated
  from provider-backed requests only.
- Current-month request limits are labeled as OpenAI request limits and continue
  to exclude local actions.
- Completion, needs-correction, and operational-failure counts continue to cover
  the whole assistant workflow.

## Deployment

No database migration is required.

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase20_local_policy_and_validation
python manage.py test assistant.tests.test_phase6_refinement
python manage.py test assistant
python manage.py test
```
