from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from core.deployment_safety import SchemaNotReadyError, assert_schema_current


class Command(BaseCommand):
    help = "Verify database, migrations, and cache for a deployed EZ360PM instance."
    requires_system_checks = "__all__"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-cache",
            action="store_true",
            help="Skip cache write/read verification.",
        )

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise CommandError("Database connectivity check returned bad data.")
        self.stdout.write(self.style.SUCCESS("Database: ok"))

        try:
            assert_schema_current(connection)
        except SchemaNotReadyError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Migrations: ok"))

        if not options["skip_cache"]:
            cache_key = "ez360pm:deployment-check"
            cache_value = "ok"
            cache.set(cache_key, cache_value, timeout=30)
            if cache.get(cache_key) != cache_value:
                raise CommandError("Cache write/read check failed.")
            cache.delete(cache_key)
            self.stdout.write(self.style.SUCCESS("Cache: ok"))

        self.stdout.write(self.style.SUCCESS("Deployment check passed."))
