from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from clients.tests.test_clients import create_client
from projects.models import Project, TimeEntry
from projects.services import create_project
from projects.tests.test_projects import project_data
from projects.time_services import (
    TimerAlreadyRunning,
    delete_manual_entry,
    pause_timer,
    resume_timer,
    save_manual_entry,
    start_timer,
    stop_timer,
)


class TimerServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        client = create_client(self.company)
        self.project = create_project(
            company=self.company,
            client=client,
            project_data=project_data(number="TIME-1"),
        )
        self.started_at = datetime(2026, 7, 21, 13, 0, tzinfo=UTC)

    def test_timer_is_persisted_and_stop_computes_duration(self):
        entry = start_timer(
            user=self.user,
            project=self.project,
            description="Schematic design",
            at=self.started_at,
        )

        reloaded = TimeEntry.objects.get(pk=entry.pk)
        self.assertIsNone(reloaded.end_time)
        self.assertTrue(reloaded.is_running)

        stopped = stop_timer(
            user=self.user,
            at=self.started_at + timedelta(minutes=90),
        )
        self.assertEqual(stopped.duration_hours, Decimal("1.50"))
        self.assertFalse(stopped.is_running)

    def test_start_rejects_second_running_timer(self):
        first = start_timer(user=self.user, project=self.project, at=self.started_at)

        with self.assertRaises(TimerAlreadyRunning) as raised:
            start_timer(
                user=self.user,
                project=self.project,
                at=self.started_at + timedelta(minutes=1),
            )

        self.assertEqual(raised.exception.entry.pk, first.pk)
        self.assertEqual(TimeEntry.objects.filter(end_time__isnull=True).count(), 1)

    def test_database_constraint_rejects_two_running_entries(self):
        TimeEntry.objects.create(
            company=self.company,
            project=self.project,
            user=self.user,
            start_time=self.started_at,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            TimeEntry.objects.create(
                company=self.company,
                project=self.project,
                user=self.user,
                start_time=self.started_at + timedelta(minutes=1),
            )

    def test_cross_company_project_is_rejected(self):
        other_company = Company.objects.create(name="Other Company")
        other_client = create_client(other_company)
        other_project = create_project(
            company=other_company,
            client=other_client,
            project_data=project_data(number="OTHER-TIME"),
        )

        with self.assertRaises(ValidationError):
            start_timer(user=self.user, project=other_project, at=self.started_at)

    def test_manual_flat_fee_time_drives_effective_rate(self):
        flat_project = create_project(
            company=self.company,
            client=self.project.client,
            project_data=project_data(
                number="FLAT-TIME",
                billing_type=Project.BillingType.FLAT_FEE,
                hourly_rate=None,
                fixed_fee=Decimal("1000.00"),
            ),
        )
        save_manual_entry(
            user=self.user,
            project=flat_project,
            entry_data={
                "start_time": self.started_at,
                "end_time": self.started_at + timedelta(hours=2),
                "description": "Design development",
                "billable": True,
            },
        )

        self.assertEqual(flat_project.actual_hours, Decimal("2.00"))
        self.assertEqual(flat_project.effective_hourly_rate, Decimal("500.00"))

    def test_invoiced_entry_cannot_be_edited(self):
        entry = save_manual_entry(
            user=self.user,
            project=self.project,
            entry_data={
                "start_time": self.started_at,
                "end_time": self.started_at + timedelta(hours=1),
                "description": "Existing work",
                "billable": True,
            },
        )
        entry.status = TimeEntry.Status.INVOICED
        entry.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            save_manual_entry(
                user=self.user,
                project=self.project,
                entry=entry,
                entry_data={
                    "start_time": self.started_at,
                    "end_time": self.started_at + timedelta(hours=2),
                    "description": "Changed work",
                    "billable": True,
                },
            )

    def test_manual_entry_can_be_deleted(self):
        entry = save_manual_entry(
            user=self.user,
            project=self.project,
            entry_data={
                "start_time": self.started_at,
                "end_time": self.started_at + timedelta(hours=1),
                "description": "Mistaken entry",
                "billable": True,
            },
        )

        delete_manual_entry(user=self.user, entry=entry)

        self.assertFalse(TimeEntry.objects.filter(pk=entry.pk).exists())

    def test_invoiced_entry_cannot_be_deleted(self):
        entry = save_manual_entry(
            user=self.user,
            project=self.project,
            entry_data={
                "start_time": self.started_at,
                "end_time": self.started_at + timedelta(hours=1),
                "description": "Already billed",
                "billable": True,
            },
        )
        entry.status = TimeEntry.Status.INVOICED
        entry.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            delete_manual_entry(user=self.user, entry=entry)
        self.assertTrue(TimeEntry.objects.filter(pk=entry.pk).exists())

    def test_running_timer_cannot_be_deleted(self):
        entry = start_timer(user=self.user, project=self.project, at=self.started_at)

        with self.assertRaises(ValidationError):
            delete_manual_entry(user=self.user, entry=entry)
        self.assertTrue(TimeEntry.objects.filter(pk=entry.pk, end_time__isnull=True).exists())

    def test_pause_freezes_duration_and_resume_excludes_the_break(self):
        start_timer(user=self.user, project=self.project, at=self.started_at)

        pause_timer(user=self.user, at=self.started_at + timedelta(minutes=30))
        entry = TimeEntry.objects.get(user=self.user)
        self.assertTrue(entry.is_paused)
        self.assertEqual(entry.duration, timedelta(minutes=30))

        # Elapsed time must stay frozen while paused, no matter how much real
        # time passes before resume is called.
        entry.refresh_from_db()
        self.assertEqual(entry.duration, timedelta(minutes=30))

        resume_timer(user=self.user, at=self.started_at + timedelta(hours=2))
        entry.refresh_from_db()
        self.assertFalse(entry.is_paused)
        # Resumed means actively ticking again, so duration now grows with
        # real time rather than staying frozen; the pause exclusion is instead
        # verified once the entry is stopped, below.

        stopped = stop_timer(user=self.user, at=self.started_at + timedelta(hours=2, minutes=15))
        self.assertEqual(stopped.duration, timedelta(minutes=45))
        self.assertEqual(stopped.duration_hours, Decimal("0.75"))

    def test_stop_while_paused_folds_the_break_into_duration(self):
        start_timer(user=self.user, project=self.project, at=self.started_at)
        pause_timer(user=self.user, at=self.started_at + timedelta(minutes=20))

        stopped = stop_timer(user=self.user, at=self.started_at + timedelta(hours=3))

        self.assertFalse(stopped.is_paused)
        self.assertEqual(stopped.duration, timedelta(minutes=20))

    def test_pause_requires_a_running_timer(self):
        with self.assertRaises(ValidationError):
            pause_timer(user=self.user)

    def test_pause_rejects_an_already_paused_timer(self):
        start_timer(user=self.user, project=self.project, at=self.started_at)
        pause_timer(user=self.user, at=self.started_at + timedelta(minutes=10))

        with self.assertRaises(ValidationError):
            pause_timer(user=self.user, at=self.started_at + timedelta(minutes=20))

    def test_resume_requires_a_paused_timer(self):
        start_timer(user=self.user, project=self.project, at=self.started_at)

        with self.assertRaises(ValidationError):
            resume_timer(user=self.user)

    def test_resume_requires_a_running_timer(self):
        with self.assertRaises(ValidationError):
            resume_timer(user=self.user)

    def test_actual_hours_excludes_paused_duration(self):
        entry = save_manual_entry(
            user=self.user,
            project=self.project,
            entry_data={
                "start_time": self.started_at,
                "end_time": self.started_at + timedelta(hours=3),
                "description": "Design session with a break",
                "billable": True,
            },
        )
        entry.paused_duration = timedelta(minutes=45)
        entry.save(update_fields=["paused_duration"])

        self.assertEqual(self.project.actual_hours, Decimal("2.25"))


class TimeEntryViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.other_user = User.objects.create_user(
            "other@example.com",
            "Strong-Test-Password-483!",
            company=self.other_company,
        )
        client = create_client(self.company)
        other_client = create_client(self.other_company, company_name="Other Client")
        self.project = create_project(
            company=self.company,
            client=client,
            project_data=project_data(number="TIME-VIEW"),
        )
        self.other_project = create_project(
            company=self.other_company,
            client=other_client,
            project_data=project_data(number="HIDDEN-TIME"),
        )
        self.client.force_login(self.user)

    def test_start_and_stop_flow_uses_persistent_header_widget(self):
        start_response = self.client.post(
            reverse("projects:timer-start"),
            {
                "project": self.project.pk,
                "description": "Measured drawings",
                "billable": "on",
            },
        )
        self.assertRedirects(start_response, reverse("projects:time-list"))

        dashboard = self.client.get(reverse("core:home"))
        self.assertContains(dashboard, "data-running-timer")
        self.assertContains(dashboard, "TIME-VIEW")

        stop_response = self.client.post(
            reverse("projects:timer-stop"),
            {"next": reverse("projects:time-list")},
        )
        self.assertRedirects(stop_response, reverse("projects:time-list"))
        self.assertFalse(TimeEntry.objects.get().is_running)

    def test_running_timer_renders_epoch_data_and_elapsed_fallback(self):
        started_at = timezone.now() - timedelta(seconds=65)
        entry = start_timer(user=self.user, project=self.project, at=started_at)

        response = self.client.get(reverse("projects:time-list"))
        html = response.content.decode()

        self.assertContains(
            response,
            f'data-timer-start-ms="{int(entry.start_time.timestamp() * 1000)}"',
            count=2,
        )
        self.assertContains(response, "data-timer-server-now-ms=", count=2)
        self.assertEqual(html.count("data-timer-clock"), 2)
        self.assertIn(">00:01:", html)
        self.assertNotIn(">00:00:00</span>", html)

    def test_start_form_rejects_other_company_project(self):
        response = self.client.post(
            reverse("projects:timer-start"),
            {"project": self.other_project.pk, "description": "No", "billable": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(TimeEntry.objects.exists())

    def test_manual_entry_create_and_project_filter(self):
        response = self.client.post(
            reverse("projects:time-create"),
            {
                "project": self.project.pk,
                "start_time_0": "2026-07-20",
                "start_time_1": "09:00",
                "duration_hours": "2",
                "duration_minutes": "30",
                "description": "Floor plans",
                "billable": "on",
            },
        )

        self.assertRedirects(response, reverse("projects:time-list"))
        entry = TimeEntry.objects.get(company=self.company)
        self.assertEqual(entry.duration_hours, Decimal("2.50"))
        self.assertEqual(entry.end_time - entry.start_time, timedelta(hours=2, minutes=30))

        list_response = self.client.get(
            reverse("projects:time-list"),
            {"project": self.project.pk},
        )
        self.assertContains(list_response, "Floor plans")
        self.assertContains(list_response, "2h 30m")
        self.assertNotContains(list_response, "HIDDEN-TIME")

    def test_manual_entry_rejects_zero_duration(self):
        response = self.client.post(
            reverse("projects:time-create"),
            {
                "project": self.project.pk,
                "start_time_0": "2026-07-20",
                "start_time_1": "09:00",
                "duration_hours": "0",
                "duration_minutes": "0",
                "description": "No time actually worked",
                "billable": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a duration greater than zero.")
        self.assertFalse(TimeEntry.objects.exists())

    def test_edit_form_prefills_duration_from_existing_entry(self):
        entry = TimeEntry.objects.create(
            company=self.company,
            project=self.project,
            user=self.user,
            start_time=datetime(2026, 7, 20, 9, tzinfo=UTC),
            end_time=datetime(2026, 7, 20, 10, 15, tzinfo=UTC),
        )

        response = self.client.get(reverse("projects:time-update", args=(entry.pk,)))

        form = response.context["form"]
        self.assertNotIn("end_time", form.fields)
        self.assertEqual(form.fields["duration_hours"].initial, 1)
        self.assertEqual(form.fields["duration_minutes"].initial, 15)

    def test_edit_paused_timer_uses_and_saves_exact_active_duration(self):
        entry = TimeEntry.objects.create(
            company=self.company,
            project=self.project,
            user=self.user,
            start_time=datetime(2026, 7, 20, 9, tzinfo=UTC),
            end_time=datetime(2026, 7, 20, 16, 2, tzinfo=UTC),
            paused_duration=timedelta(hours=1, minutes=2),
            description="Design hours",
        )

        get_response = self.client.get(
            reverse("projects:time-update", args=(entry.pk,))
        )
        form = get_response.context["form"]
        self.assertEqual(form.fields["duration_hours"].initial, 6)
        self.assertEqual(form.fields["duration_minutes"].initial, 0)

        post_response = self.client.post(
            reverse("projects:time-update", args=(entry.pk,)),
            {
                "project": self.project.pk,
                "start_time_0": "2026-07-20",
                "start_time_1": "09:00",
                "duration_hours": "6",
                "duration_minutes": "0",
                "description": "Design hours",
                "billable": "on",
            },
        )

        self.assertRedirects(post_response, reverse("projects:time-list"))
        entry.refresh_from_db()
        self.assertEqual(entry.duration, timedelta(hours=6))
        self.assertEqual(entry.duration_hours, Decimal("6.00"))
        self.assertEqual(
            entry.end_time - entry.start_time,
            timedelta(hours=7, minutes=2),
        )

    def test_manual_entry_create_defaults_project_from_query_param(self):
        response = self.client.get(
            reverse("projects:time-create"), {"project": self.project.pk}
        )

        self.assertEqual(
            response.context["form"].initial.get("project"), str(self.project.pk)
        )

    def test_project_detail_links_default_to_current_project(self):
        response = self.client.get(reverse("projects:detail", args=(self.project.pk,)))

        self.assertContains(
            response,
            f"{reverse('projects:time-create')}?project={self.project.pk}",
        )

    def test_header_start_timer_link_defaults_to_project_being_viewed(self):
        response = self.client.get(reverse("projects:detail", args=(self.project.pk,)))

        self.assertContains(
            response,
            f"{reverse('projects:timer-start')}?project={self.project.pk}",
        )

    def test_other_company_entry_cannot_be_edited(self):
        hidden = TimeEntry.objects.create(
            company=self.other_company,
            project=self.other_project,
            user=self.other_user,
            start_time=datetime(2026, 7, 20, 9, tzinfo=UTC),
            end_time=datetime(2026, 7, 20, 10, tzinfo=UTC),
        )

        response = self.client.get(reverse("projects:time-update", args=(hidden.pk,)))

        self.assertEqual(response.status_code, 404)

    def test_invoiced_entry_has_no_edit_endpoint(self):
        entry = TimeEntry.objects.create(
            company=self.company,
            project=self.project,
            user=self.user,
            start_time=datetime(2026, 7, 20, 9, tzinfo=UTC),
            end_time=datetime(2026, 7, 20, 10, tzinfo=UTC),
            status=TimeEntry.Status.INVOICED,
        )

        response = self.client.get(reverse("projects:time-update", args=(entry.pk,)))

        self.assertEqual(response.status_code, 404)

    def test_manual_entry_delete_flow(self):
        entry = TimeEntry.objects.create(
            company=self.company,
            project=self.project,
            user=self.user,
            start_time=datetime(2026, 7, 20, 9, tzinfo=UTC),
            end_time=datetime(2026, 7, 20, 10, tzinfo=UTC),
            description="Site visit",
        )

        response = self.client.post(reverse("projects:time-delete", args=(entry.pk,)))

        self.assertRedirects(response, reverse("projects:time-list"))
        self.assertFalse(TimeEntry.objects.filter(pk=entry.pk).exists())

    def test_invoiced_entry_delete_is_rejected_with_message(self):
        entry = TimeEntry.objects.create(
            company=self.company,
            project=self.project,
            user=self.user,
            start_time=datetime(2026, 7, 20, 9, tzinfo=UTC),
            end_time=datetime(2026, 7, 20, 10, tzinfo=UTC),
            status=TimeEntry.Status.INVOICED,
        )

        response = self.client.post(
            reverse("projects:time-delete", args=(entry.pk,)), follow=True
        )

        self.assertRedirects(response, reverse("projects:time-list"))
        self.assertContains(response, "Invoiced time cannot be deleted.")
        self.assertTrue(TimeEntry.objects.filter(pk=entry.pk).exists())

    def test_other_company_entry_cannot_be_deleted(self):
        hidden = TimeEntry.objects.create(
            company=self.other_company,
            project=self.other_project,
            user=self.other_user,
            start_time=datetime(2026, 7, 20, 9, tzinfo=UTC),
            end_time=datetime(2026, 7, 20, 10, tzinfo=UTC),
        )

        response = self.client.post(reverse("projects:time-delete", args=(hidden.pk,)))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(TimeEntry.objects.filter(pk=hidden.pk).exists())

    def test_pause_and_resume_flow_via_header_widget(self):
        started_at = timezone.now() - timedelta(minutes=10)
        start_timer(user=self.user, project=self.project, at=started_at)

        pause_response = self.client.post(reverse("projects:timer-pause"), follow=True)
        self.assertRedirects(pause_response, reverse("projects:time-list"))
        self.assertContains(pause_response, "Timer paused.")
        self.assertContains(pause_response, "Paused")
        self.assertContains(pause_response, 'data-timer-paused="true"')
        self.assertContains(pause_response, reverse("projects:timer-resume"))

        resume_response = self.client.post(reverse("projects:timer-resume"), follow=True)
        self.assertRedirects(resume_response, reverse("projects:time-list"))
        self.assertContains(resume_response, "Timer resumed.")
        self.assertContains(resume_response, 'data-timer-paused="false"')
        self.assertContains(resume_response, reverse("projects:timer-pause"))

        self.assertFalse(TimeEntry.objects.get(user=self.user).is_paused)

    def test_pause_without_a_running_timer_shows_error(self):
        response = self.client.post(reverse("projects:timer-pause"), follow=True)

        self.assertRedirects(response, reverse("projects:time-list"))
        self.assertContains(response, "No timer is currently running.")

    def test_resume_without_a_paused_timer_shows_error(self):
        start_timer(user=self.user, project=self.project, at=timezone.now() - timedelta(minutes=5))

        response = self.client.post(reverse("projects:timer-resume"), follow=True)

        self.assertRedirects(response, reverse("projects:time-list"))
        self.assertContains(response, "This timer is not paused.")

    def test_paused_entry_shows_paused_badge_instead_of_running(self):
        start_timer(user=self.user, project=self.project, at=timezone.now() - timedelta(minutes=10))
        self.client.post(reverse("projects:timer-pause"))

        list_response = self.client.get(reverse("projects:time-list"))
        self.assertContains(list_response, "Timer paused")  # running-card banner
        self.assertContains(list_response, "status-badge--paused")  # ledger row badge

        detail_response = self.client.get(reverse("projects:detail", args=(self.project.pk,)))
        self.assertContains(detail_response, "Paused")
        self.assertNotContains(detail_response, ">Running<")

    def test_get_on_timer_action_urls_redirects_instead_of_405(self):
        for name in ("projects:timer-stop", "projects:timer-pause", "projects:timer-resume"):
            response = self.client.get(reverse(name))
            self.assertRedirects(response, reverse("projects:time-list"))
