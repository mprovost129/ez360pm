# EZ360PM AI Assistant V1.32

## Optional AI startup configuration resilience

AI-only environment settings are now parsed through a defensive, dependency-free
configuration layer.

- Invalid AI booleans, integers, decimals, and model-pricing JSON no longer crash
  Django settings import.
- When AI is globally disabled, malformed AI-only values fall back to safe defaults
  and appear as `assistant.W007` deployment warnings.
- When AI is enabled, the same malformed values appear as deployment-blocking
  `assistant.E028` errors.
- Unsupported `AI_PROVIDER` values are rejected as `assistant.E029`; OpenAI remains
  the only configured provider.
- Semantic AI validation is skipped when the optional feature is disabled, so stale
  inactive AI settings cannot block deployment of the ordinary CRM, project,
  document, payment, or reporting workflows.
- Added parser and deployment-check regression tests.

No database migration or static-file collection is required.
