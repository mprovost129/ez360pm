# EZ360PM AI Assistant V1.24

## Confirmation validation outcomes

V1.24 closes an inconsistency between assistant preparation and confirmation.
Ordinary business validation problems are now classified as **Needs correction**
at both stages instead of becoming operational AI failures after the user clicks
Confirm.

Examples include:

- A duplicate client created after the original preview
- A project, invoice, or contact changed after preview
- A status transition that is no longer allowed
- An ambiguous record discovered during final execution

These outcomes remain fully auditable, but they no longer count toward the company
AI circuit breaker.

## Cleaner user messages

Django validation errors are now flattened into normal sentences. The assistant no
longer displays Python list formatting such as `['Message']` in the drawer or action
confirmation response.

## Reporting

- Action history includes a distinct **Needs correction** status.
- The assistant drawer removes a confirmation card that is no longer valid.
- The Action Center disables a blocked card and directs the user to prepare a corrected action.
- Usage by capability separates needs-correction outcomes from true failures.
- Pilot failure counts exclude legacy action rows with `domain_validation`.
- Migration `assistant.0011_aiactionattempt_blocked_status` reclassifies legacy
  domain-validation action failures to the new blocked status.

## Deployment

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant.tests.test_phase24_confirmation_validation
python manage.py test assistant
python manage.py test
```
