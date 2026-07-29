# EZ360PM AI Assistant V1.31 Validation

Run in the normal project environment:

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase29_optional_integration
python manage.py test assistant.tests.test_phase30_global_feature_gate
python manage.py test assistant.tests.test_phase31_lazy_ai_provisioning
python manage.py test assistant
python manage.py test
```

Manual checks:

1. Set `AI_ASSISTANT_ENABLED=false` and restart the application.
2. Create a Company and User through the normal bootstrap/admin workflow.
3. Confirm no `AICompanySettings` or `AIUserAccess` rows are created.
4. Create or edit a proposal/invoice and confirm ordinary document behavior works
   without assistant-table writes.
5. Set `AI_ASSISTANT_ENABLED=true`, restart, and create another Company and User.
6. Confirm those records still do not automatically create AI policy/access rows.
7. Open an ordinary authenticated page and confirm the drawer may use deployment
   defaults without persisting a policy row.
8. Open Company Settings -> AI Settings or submit the first assistant request and
   confirm the company policy is created at that point.
9. Switch the policy to Selected users and confirm a new user has no access until
   staff explicitly grant it in AI Pilot Operations.
