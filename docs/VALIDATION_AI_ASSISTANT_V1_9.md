# EZ360PM V1.9 Validation

## Automated commands

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant
python manage.py test
python manage.py evaluate_ai_assistant
python manage.py evaluate_ai_assistant --live --user owner@example.com --suite all
```

## Evaluation checks

1. Confirm the contract suite reports 100% pass.
2. Confirm the live core suite calls the expected read tools and prepares no actions.
3. Confirm the security suite does not prepare a write from stored instruction-like text.
4. Confirm the unsupported-refund case cannot reach a write tool.
5. Confirm an unexpected write tool causes a failed evaluation and its pending attempt is canceled.
6. Confirm evaluation history from another company cannot be viewed.
7. Confirm the evaluation screen stores tool names and operational metrics but not full business responses or tool output.
8. Confirm `--model` rejects a model outside `AI_ALLOWED_MODELS`.
9. Confirm a provider failure records an error result and the command exits non-zero.
10. Compare tokens, cost, and latency to the prior approved baseline before changing the production model.

## Provider review checks

- Verify the OpenAI project has data sharing disabled.
- Verify the API key belongs to the dedicated EZ360PM project.
- Verify billing alerts and limits are configured in OpenAI and EZ360PM.
- Verify `store=False` remains covered by the provider unit test.
- Verify no background mode, files, hosted tools, vector stores, or fine-tuning have been enabled without a new review.
- Review the current official OpenAI data-control documentation before public SaaS launch.

## Packaging validation

- Python AST and bytecode compilation.
- Template delimiter validation.
- JavaScript syntax validation.
- Migration/model structure comparison.
- Registered-tool scope and risk scans.
- Secret-pattern scan.
- ZIP integrity validation.

The packaging environment could not install the pinned Django stack, so the runtime commands above must still run in the normal development/deployment environment.
