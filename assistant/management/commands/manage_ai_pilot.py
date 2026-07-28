from django.core.management.base import BaseCommand, CommandError

from accounts.models import Company, User
from assistant.models import AIUserAccess
from assistant.policies import get_company_policy, resume_company_ai, suspend_company_ai


class Command(BaseCommand):
    help = "Suspend/resume company AI or grant/revoke selected-user pilot access."

    def add_arguments(self, parser):
        parser.add_argument("--company-id", type=int, required=True)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--suspend", action="store_true")
        group.add_argument("--resume", action="store_true")
        group.add_argument("--grant-user")
        group.add_argument("--revoke-user")
        parser.add_argument("--reason", default="Manual operations command")

    def handle(self, *args, **options):
        del args
        company = Company.objects.filter(pk=options["company_id"]).first()
        if company is None:
            raise CommandError("Company not found.")
        policy = get_company_policy(company)

        if options["suspend"]:
            changed = suspend_company_ai(policy, reason=options["reason"])
            self.stdout.write(self.style.WARNING("AI suspended." if changed else "AI was already suspended."))
            return
        if options["resume"]:
            changed = resume_company_ai(policy)
            self.stdout.write(self.style.SUCCESS("AI resumed." if changed else "AI was not suspended."))
            return

        email = options["grant_user"] or options["revoke_user"]
        user = User.objects.filter(company=company, email__iexact=email).first()
        if user is None:
            raise CommandError("A company user with that email was not found.")
        enabled = bool(options["grant_user"])
        access, _created = AIUserAccess.objects.update_or_create(
            user=user,
            defaults={"company": company, "enabled": enabled},
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Selected-user AI access {'granted' if access.enabled else 'revoked'} for {user.email}."
            )
        )
