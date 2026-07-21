from django.contrib.auth.base_user import BaseUserManager
from django.db import models


class CompanyScopedQuerySet(models.QuerySet):
    """Query helpers shared by records with a direct company foreign key."""

    def for_company(self, company):
        if company is None:
            return self.none()
        return self.filter(company=company)


class CompanyScopedManager(models.Manager.from_queryset(CompanyScopedQuerySet)):
    pass


class UserQuerySet(CompanyScopedQuerySet):
    pass


class UserManager(BaseUserManager.from_queryset(UserQuerySet)):
    use_in_migrations = True

    @staticmethod
    def normalize_login_email(email):
        return BaseUserManager.normalize_email(email).strip().lower()

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email address is required.")
        if not extra_fields.get("company") and not extra_fields.get("company_id"):
            raise ValueError("A company is required.")

        # Django's createsuperuser command cleans a ForeignKey prompt to its raw
        # primary-key value and passes it under the field name. Model
        # construction expects either a Company instance under ``company`` or a
        # raw value under ``company_id``.
        company = extra_fields.get("company")
        if company is not None and not isinstance(company, models.Model):
            extra_fields["company_id"] = extra_fields.pop("company")

        email = self.normalize_login_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)
