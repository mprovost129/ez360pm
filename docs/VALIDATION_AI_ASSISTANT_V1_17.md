# EZ360PM AI Assistant V1.17 Validation

## Static validation completed in the packaging environment

- Parsed and compiled 216 Python files.
- Verified focused create-client requests expose only `create_client`.
- Verified prepared writes return without a second provider request.
- Verified an unexposed tool call fails closed.
- Verified ordinary project-detail changes do not route to the status workflow.
- Verified the configurable tool-call ceiling and deployment check.
- Verified existing tool schemas still exclude company and user identifiers.
- Verified no migration is required.
- Scanned for obvious committed OpenAI secrets.
- Verified 57 templates and 4 JavaScript files passed static syntax checks.
- Verified ZIP integrity after packaging.

## Required runtime validation

Run the full Django suite and a live OpenAI test in the normal development or
deployment environment. In particular, test:

1. `Create a client for <name> ...` with all available fields in one message.
2. A client with only first and last name.
3. A possible duplicate email or phone.
4. A client request missing a required name, confirming the assistant asks one
   concise question rather than searching broadly.
5. Project-address and project-status changes as separate commands.
