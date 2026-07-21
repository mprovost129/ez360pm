import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import Company
from core.data_audit import audit_data


class Command(BaseCommand):
    help = "Read-only audit of EZ360PM financial, document, and time relationships."

    def add_arguments(self, parser):
        parser.add_argument("--company-id", type=int)
        parser.add_argument(
            "--pending-minutes",
            type=int,
            default=15,
            help="Age at which a pending document delivery becomes a warning.",
        )
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument(
            "--fail-on-warning",
            action="store_true",
            help="Return a failure status when warnings are found.",
        )

    def handle(self, *args, **options):
        company_id = options["company_id"]
        if company_id is not None and not Company.objects.filter(pk=company_id).exists():
            raise CommandError(f"Company {company_id} does not exist.")
        if options["pending_minutes"] < 1:
            raise CommandError("--pending-minutes must be at least 1.")

        issues = audit_data(
            company_id=company_id,
            pending_minutes=options["pending_minutes"],
        )
        errors = sum(issue.severity == "error" for issue in issues)
        warnings = sum(issue.severity == "warning" for issue in issues)
        payload = {
            "checked_at": timezone.now().isoformat(),
            "company_id": company_id,
            "errors": errors,
            "warnings": warnings,
            "issues": [issue.to_dict() for issue in issues],
        }

        if options["as_json"]:
            self.stdout.write(json.dumps(payload, sort_keys=True))
        else:
            for issue in issues:
                self.stdout.write(
                    f"[{issue.severity.upper()}] {issue.code} "
                    f"{issue.model}#{issue.object_id}: {issue.detail}"
                )
            self.stdout.write(f"Data audit: {errors} error(s), {warnings} warning(s).")

        if errors or (warnings and options["fail_on_warning"]):
            raise CommandError("Data audit failed.")
        if not options["as_json"]:
            self.stdout.write(self.style.SUCCESS("Data audit passed."))
