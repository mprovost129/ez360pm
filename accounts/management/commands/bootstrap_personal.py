import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.managers import UserManager
from accounts.models import Company, User


class Command(BaseCommand):
    help = "Create or update the single personal-build company and owner account."

    def add_arguments(self, parser):
        parser.add_argument("--company-name", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--first-name", default="")
        parser.add_argument("--last-name", default="")
        parser.add_argument(
            "--password-env",
            default="EZ360PM_OWNER_PASSWORD",
            help="Environment variable containing the initial owner password.",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Fail instead of prompting when a new password is required.",
        )

    def handle(self, *args, **options):
        company_name = options["company_name"].strip()
        email = UserManager.normalize_login_email(options["email"])
        if not company_name:
            raise CommandError("Company name cannot be blank.")
        if not email:
            raise CommandError("Email cannot be blank.")

        password = os.environ.get(options["password_env"], "")
        existing_user = User.objects.filter(email__iexact=email).first()
        if existing_user is None and not password:
            if options["no_input"]:
                raise CommandError(
                    f"Set {options['password_env']} when using --no-input."
                )
            password = self._prompt_for_password()

        if password:
            validate_password(password, user=existing_user)

        with transaction.atomic():
            user = User.objects.select_for_update().filter(email__iexact=email).first()
            if user is not None:
                company = user.company
                company.name = company_name
                if not company.email:
                    company.email = email
                company.save(update_fields=["name", "email"])
                created = False
            else:
                matches = Company.objects.select_for_update().filter(name=company_name)
                if matches.count() > 1:
                    raise CommandError(
                        "Multiple companies have that name; initialize the owner in admin."
                    )
                company = matches.first()
                if company is None:
                    company = Company.objects.create(name=company_name, email=email)
                user = User(
                    email=email,
                    company=company,
                    first_name=options["first_name"].strip(),
                    last_name=options["last_name"].strip(),
                    is_active=True,
                    is_staff=True,
                    is_superuser=True,
                )
                created = True

            user.first_name = options["first_name"].strip() or user.first_name
            user.last_name = options["last_name"].strip() or user.last_name
            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            if password:
                user.set_password(password)
            user.save()

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"{action} owner {user.email} for {company.name}.")
        )

    @staticmethod
    def _prompt_for_password():
        first = getpass.getpass("Owner password: ")
        second = getpass.getpass("Owner password (again): ")
        if first != second:
            raise CommandError("Passwords do not match.")
        if not first:
            raise CommandError("Password cannot be blank.")
        return first

