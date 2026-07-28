import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from assistant.readiness import build_readiness_report


class Command(BaseCommand):
    help = "Check one company's OpenAI assistant controlled-use readiness."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            required=True,
            help="Email/username of a user in the company to evaluate.",
        )
        parser.add_argument(
            "--output",
            help="Optional path for a JSON readiness report.",
        )
        parser.add_argument(
            "--no-fail",
            action="store_true",
            help="Return exit code 0 even when required checks fail.",
        )

    def handle(self, *args, **options):
        del args
        User = get_user_model()
        identifier = options["user"]
        user = User.objects.filter(email=identifier).first()
        if user is None:
            user = User.objects.filter(username=identifier).first()
        if user is None:
            raise CommandError("No matching user was found.")
        if not getattr(user, "company_id", None):
            raise CommandError("The selected user is not assigned to a company.")

        report = build_readiness_report(user)
        payload = report.as_dict()
        for item in report.checks:
            marker = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[item.status]
            self.stdout.write(f"[{marker}] {item.title}: {item.detail}")
        self.stdout.write(
            f"Model={report.model}; requests={report.requests_used}/{report.request_limit}; "
            f"estimated_cost=${report.cost_used:.6f}/${report.cost_limit:.2f}"
        )

        if options["output"]:
            output_path = Path(options["output"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, indent=2) + "\n")
            self.stdout.write(f"Wrote {output_path}")

        if report.ready:
            self.stdout.write(self.style.SUCCESS("AI assistant is ready for controlled use."))
            return
        message = (
            f"AI assistant is not ready: {report.failed_count} required check(s) failed "
            f"and {report.warning_count} warning(s) remain."
        )
        if options["no_fail"]:
            self.stdout.write(self.style.WARNING(message))
            return
        raise CommandError(message)
