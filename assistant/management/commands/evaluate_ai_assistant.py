import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from assistant.evaluations import run_contract_evaluation, run_live_evaluation


class Command(BaseCommand):
    help = "Run EZ360PM AI contract checks and optional read-only live OpenAI evaluations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--live",
            action="store_true",
            help="Run the read-only live OpenAI suite in addition to contract checks.",
        )
        parser.add_argument("--user", help="Company user email required for --live.")
        parser.add_argument(
            "--suite",
            choices=("core", "security", "all"),
            default="all",
        )
        parser.add_argument("--model", help="Allowlisted OpenAI model override.")
        parser.add_argument("--output", help="Optional JSON summary path.")
        parser.add_argument(
            "--no-persist-contract",
            action="store_true",
            help="Do not store the contract-only run in the database.",
        )

    def handle(self, *args, **options):
        contract_run, contract_results = run_contract_evaluation(
            persist=not options["no_persist_contract"]
        )
        contract_passed = all(item["passed"] for item in contract_results)
        for item in contract_results:
            marker = self.style.SUCCESS("PASS") if item["passed"] else self.style.ERROR("FAIL")
            self.stdout.write(f"{marker} {item['case_id']}: {item['title']}")

        payload = {
            "contract": {
                "passed": contract_passed,
                "run_id": contract_run.pk if contract_run else None,
                "cases": contract_results,
            }
        }
        live_run = None
        if options["live"]:
            if not options["user"]:
                raise CommandError("--user is required with --live.")
            try:
                user = User.objects.select_related("company").get(email=options["user"])
            except User.DoesNotExist as exc:
                raise CommandError("No user exists with that email.") from exc
            live_run = run_live_evaluation(
                user=user,
                suite=options["suite"],
                model=options["model"],
            )
            payload["live"] = {
                "passed": live_run.status == live_run.Status.PASSED,
                "run_id": live_run.pk,
                "suite": live_run.suite,
                "model": live_run.model,
                "passed_cases": live_run.passed_cases,
                "failed_cases": live_run.failed_cases,
                "total_tokens": live_run.total_tokens,
                "estimated_cost_usd": str(live_run.estimated_cost_usd),
            }
            style = self.style.SUCCESS if payload["live"]["passed"] else self.style.ERROR
            self.stdout.write(
                style(
                    f"LIVE {live_run.status.upper()}: {live_run.passed_cases}/"
                    f"{live_run.total_cases} cases passed using {live_run.model}."
                )
            )

        if options["output"]:
            path = Path(options["output"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
            self.stdout.write(f"Wrote {path}")

        if not contract_passed or (live_run and live_run.status != live_run.Status.PASSED):
            raise CommandError("One or more AI evaluation checks failed.")
