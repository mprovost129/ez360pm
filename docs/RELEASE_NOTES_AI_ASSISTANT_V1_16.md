# EZ360PM AI Assistant V1.16 Release Notes

## Purpose

V1.16 closes the final concrete OpenAI operational gap found after the V1.15
completion audit. It adds troubleshooting and model-stability controls without
adding another AI capability or widening model authority.

## OpenAI request observability

- Generates one UUID for every logical Responses API call.
- Sends it as `X-Client-Request-Id` through the official OpenAI Python SDK.
- Persists the client-generated ID before the network call.
- Persists OpenAI response request IDs from successful and rejected calls.
- Keeps the client-generated ID when a timeout or connection failure produces no
  provider response ID.
- Exports both identifier types through the metadata-only AI audit CSV.
- Preserves IDs per tool round because one assistant turn may make several API
  calls.

## OpenAI project scoping

The provider now explicitly accepts optional `OPENAI_ORG_ID` and
`OPENAI_PROJECT_ID` settings. They are passed to the official SDK without being
stored in database records or exposed to model tools.

## Model stability

- Adds `AI_WARN_ON_UNPINNED_MODEL=true`.
- Dated model snapshots pass the stability check.
- Mutable aliases produce an informational Django check and a readiness warning,
  not a startup failure.
- Existing configuration fingerprints continue to invalidate old evaluations
  after model, prompt, tool, schema, SDK, or provider-path changes.

## Evaluation and tests

- The static contract suite verifies guarded Responses API options and
  `X-Client-Request-Id` support.
- Provider tests verify the exact request header and returned diagnostic values.
- Assistant service tests verify unique client IDs across multiple tool rounds and
  persistence on `AIInteraction`.

## Migration

Apply `assistant.0010_aiinteraction_provider_client_request_ids`.

## Safety boundary

No new read, write, document, sending, payment, refund, scheduling, or autonomous
action was added. All prior confirmation, tenant-isolation, explicit-intent, and
financial-safety controls remain unchanged.
