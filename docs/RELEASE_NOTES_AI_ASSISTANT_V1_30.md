# EZ360PM AI Assistant V1.30

## Global feature-gate isolation

Every route in the `assistant` URL namespace is now wrapped by the application-level
`AI_ASSISTANT_ENABLED` feature gate. When the feature is disabled, direct requests
return HTTP 404 before any assistant view executes.

This closes the remaining optional-integration side effect: manually requesting an
assistant URL could previously create an `AICompanySettings` row before the view
reported that AI was unavailable.

The browser script also checks that the assistant drawer exists before querying any
of its child controls. This keeps the shared JavaScript safe if it is accidentally
loaded on a page where the optional drawer is not rendered.

No database migration is required. Run `collectstatic` because `assistant.js` changed.
