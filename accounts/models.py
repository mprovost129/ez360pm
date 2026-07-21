from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower

from .managers import CompanyScopedManager, UserManager


class Company(models.Model):
    name = models.CharField(max_length=255)
    address_1 = models.CharField(max_length=255, blank=True)
    address_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True, default="United States")
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to="company_logos/%Y/%m/", blank=True, null=True)
    default_hourly_rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    accept_payments_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name", "pk")
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name


class CompanyOwnedModel(models.Model):
    """Base for top-level records that belong directly to one company."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT)

    objects = CompanyScopedManager()

    class Meta:
        abstract = True


class User(AbstractUser):
    username = None
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="users",
    )
    email = models.EmailField(unique=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["company"]

    class Meta:
        ordering = ("email",)
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="accounts_user_email_ci_unique",
            ),
        ]

    def save(self, *args, **kwargs):
        self.email = UserManager.normalize_login_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email
