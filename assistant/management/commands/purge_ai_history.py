from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from assistant.models import (
    AICompanySettings,
    AIEvent,
    AIInsightDismissal,
    AIInteraction,
)


class Command(BaseCommand):
    help = (
        "Delete old read-only AI interactions and operational events using each "
        "company's retention setting. Write audits, AI draft-quality metadata, feedback, and incident-linked interactions are retained."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Override each company's configured retention period.",
        )
        parser.add_argument("--company-id", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        del args
        override_days = options["days"]
        if override_days is not None and override_days < 1:
            raise CommandError("--days must be at least 1.")

        policies = AICompanySettings.objects.select_related("company").order_by("company_id")
        if options["company_id"] is not None:
            policies = policies.filter(company_id=options["company_id"])
        if not policies.exists():
            raise CommandError("No matching company AI settings were found.")

        now = timezone.now()
        totals = {"interactions": 0, "events": 0, "dismissals": 0}
        for policy in policies.iterator():
            days = override_days or policy.interaction_retention_days
            cutoff = now - timedelta(days=days)
            events = AIEvent.objects.filter(
                company=policy.company,
                created_at__lt=cutoff,
                action_attempt__isnull=True,
            )
            interactions = AIInteraction.objects.filter(
                company=policy.company,
                created_at__lt=cutoff,
                action_attempts__isnull=True,
                feedback__isnull=True,
                incidents__isnull=True,
            )
            dismissals = AIInsightDismissal.objects.filter(
                company=policy.company,
                dismissed_until__lt=now,
            )
            counts = {
                "events": events.count(),
                "interactions": interactions.count(),
                "dismissals": dismissals.count(),
            }
            for key, value in counts.items():
                totals[key] += value
            if not options["dry_run"]:
                # Remove operational events first so old read-only interactions are no
                # longer referenced by SET_NULL event rows.
                events.delete()
                interactions.delete()
                dismissals.delete()
            self.stdout.write(
                f"{policy.company}: retention={days} days; "
                f"interactions={counts['interactions']}, events={counts['events']}, "
                f"dismissals={counts['dismissals']}"
            )

        prefix = "Would delete" if options["dry_run"] else "Deleted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix} {totals['interactions']} interaction(s), "
                f"{totals['events']} event(s), and "
                f"{totals['dismissals']} expired dismissal(s)."
            )
        )
