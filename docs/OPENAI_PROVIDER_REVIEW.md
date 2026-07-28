# OpenAI API Provider Security and Data-Processing Review

**Review date:** 2026-07-27  
**Scope:** EZ360PM use of the OpenAI Responses API through the official Python SDK  
**Status:** Initial technical/provider review complete; legal and customer-facing SaaS review still required before public launch.

## Current EZ360PM controls

- Requests use the official OpenAI Python SDK and the Responses API.
- `store=False` is set on every request.
- Background mode is not used.
- Parallel tool calls are disabled.
- Only server-registered strict function tools are supplied.
- Company and user identity are never accepted from the model.
- Retrieved business text is labeled as untrusted data.
- Full prompts and full responses are not stored in the EZ360PM database.
- Redacted summaries can be disabled per company.
- Every company has request, cost, retention, model, and capability controls.
- External and financial actions require an exact in-app confirmation.

## Provider findings

### Model training

OpenAI states that API inputs and outputs are not used to train its models by default. Data sharing for model improvement is an explicit organization-level opt-in. EZ360PM should keep provider data-sharing disabled unless a separate reviewed decision is made.

### Retention

OpenAI states that API inputs and outputs may be retained for up to 30 days for service delivery and abuse monitoring unless the organization qualifies for and enables Zero Data Retention. The Responses API has application-state retention behavior documented separately. EZ360PM sets `store=False`, does not use background mode, and should not describe this as Zero Data Retention unless the OpenAI organization is actually approved and configured for ZDR.

### Security and compliance

OpenAI states that business data is encrypted at rest and in transit and that the API platform has SOC 2 Type 2 coverage. OpenAI offers a Data Processing Addendum and, for qualifying use cases, Zero Data Retention and a Business Associate Agreement.

## Required operator actions before production

1. Use a dedicated OpenAI API project for EZ360PM.
2. Restrict API keys to the minimum required project and rotate them on a documented schedule.
3. Keep OpenAI organization data-sharing/model-improvement settings disabled.
4. Confirm billing alerts and provider spend limits in addition to EZ360PM limits.
5. Confirm the selected model remains in the deployment allowlist.
6. Run the EZ360PM contract and live read-only evaluation suites after every model, prompt, tool, or SDK change.
7. Review OpenAI data-control documentation at least annually and when changing endpoints or enabling new API features.
8. Execute an OpenAI DPA before onboarding public SaaS customers when required by business or legal obligations.
9. Determine whether the public SaaS use case requires ZDR; do not promise ZDR without written confirmation and organization-level configuration.
10. Complete legal review of the customer privacy notice, terms, subprocessors, retention representations, and cross-border processing before public launch.

## Features that require a new review

- Background Responses mode
- File or image uploads to OpenAI
- Vector stores, file search, or hosted tools
- Fine-tuning
- Audio storage or transcription
- Provider-side conversation state
- Automated/scheduled sending
- Additional model providers
- Public SaaS access by customer companies

## Official sources reviewed

- OpenAI Enterprise Privacy: https://openai.com/enterprise-privacy/
- OpenAI Business Data Privacy, Security, and Compliance: https://openai.com/business-data/
- OpenAI Security and Privacy: https://openai.com/security-and-privacy/
- OpenAI API Data Controls: https://platform.openai.com/docs/models/default-usage-policies-by-endpoint
- OpenAI API data-sharing controls: https://help.openai.com/en/articles/10306912
- OpenAI API quickstart and Responses API guidance: https://platform.openai.com/docs/quickstart

This document is an engineering review, not legal advice or a certification of compliance.

## V1.12 local draft-quality telemetry

`AIDocumentDraftReview` is generated and updated inside EZ360PM from local
Document lifecycle events. These snapshots are not sent to OpenAI. Customer-facing
text is represented by local SHA-256 hashes, and the report/export contains only
metadata such as document type/number, changed field categories, totals, revision
counts, and timestamps.

## V1.13 draft-revision data handling

The provider may receive the current editable draft fields needed to propose a
revision, subject to the same company policy, request limits, security envelope,
and `store=False` request configuration as other assistant tools. EZ360PM's
long-lived draft-quality tracker stores only hashes and structural/financial
metadata. The revision confirmation and ordinary document record remain the
system of record; no separate readable copy of the revised document is added to
analytics tables.



## Request troubleshooting and project scope

EZ360PM sends a unique `X-Client-Request-Id` on every logical Responses API call
and stores it alongside any request ID returned by OpenAI. This provides a local
identifier for timeouts where no response header is available. The integration
also supports `OPENAI_ORG_ID` and `OPENAI_PROJECT_ID` so deployment scope can be
made explicit when a credential can reach multiple OpenAI resources. These values
remain server-side and are never exposed as model tool arguments.

Dated model snapshots are preferred when stable behavior is required. Mutable
aliases are allowed but require especially careful evaluation freshness because
the provider may update the alias without an EZ360PM code change.
