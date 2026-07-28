# V1.5 Validation Checklist

- [x] Python syntax/AST validation for source and migrations.
- [x] JavaScript syntax validation for the final-review interaction.
- [x] Template delimiter validation.
- [x] Static scan confirms no AI tool accepts company or user IDs.
- [x] Static scan confirms no refund or money-movement tool is registered.
- [x] Regression tests added for issue/send success, stale confirmation, tenant recipient isolation, delivery failure, manual payment, void protection, and double confirmation.
- [ ] `manage.py makemigrations --check` in the project runtime.
- [ ] `manage.py check --deploy` in the project runtime.
- [ ] Full Django test suite in the project runtime.
- [ ] Manual SMTP delivery and failure drill.
- [ ] Manual stale-document and stale-recipient drill.
