import json
import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# config/Settings/base.py -> .parent = Settings, .parent = config, .parent = project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load .env from project root
load_dotenv(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ['SECRET_KEY']

# Application definition
INSTALLED_APPS = [
    'config.apps.JetDashboardConfig',
    'config.apps.JetConfig',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'axes',
    # Local
    'accounts.apps.AccountsConfig',
    'clients.apps.ClientsConfig',
    'projects.apps.ProjectsConfig',
    'intake.apps.IntakeConfig',
    'documents.apps.DocumentsConfig',
    'core.apps.CoreConfig',
    'assistant.apps.AssistantConfig',
]

AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'documents.middleware.PublicDocumentSecurityHeadersMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.SuperuserAdministrationMiddleware',
    'axes.middleware.AxesMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Axes — brute-force login protection
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hours
AXES_LOCKOUT_CALLABLE = None  # uses default 403 response

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'intake.context_processors.quick_note',
                'projects.context_processors.running_timer',
                'assistant.context_processors.assistant_status',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.environ.get('TIME_ZONE', 'America/New_York')
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.environ.get('MEDIA_ROOT', BASE_DIR / 'media'))

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Auth
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'core:home'
LOGOUT_REDIRECT_URL = 'accounts:login'

# Cache — overridden per environment
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.environ.get('DJANGO_ROOT_LOG_LEVEL', 'WARNING'),
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
    },
}

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ['DB_NAME'],
        'USER': os.environ['DB_USER'],
        'PASSWORD': os.environ['DB_PASSWORD'],
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'OPTIONS': (
            {'sslmode': os.environ['DB_SSLMODE']}
            if os.environ.get('DB_SSLMODE')
            else {}
        ),
    }
}

# Email
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', 10))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'webmaster@localhost')
PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', 'http://localhost:8000').rstrip('/')

# Stripe Checkout. Both values are intentionally blank until configured.
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_FEE_RECONCILIATION_BATCH_SIZE = int(
    os.environ.get('STRIPE_FEE_RECONCILIATION_BATCH_SIZE', '50')
)

# EZ360PM AI assistant. Disabled by default so ordinary workflows never depend on AI.
AI_ASSISTANT_ENABLED = os.environ.get("AI_ASSISTANT_ENABLED", "false").lower() in {
    "1", "true", "yes", "on"
}

# Company defaults are optional. When omitted, they follow the application-level
# enablement so local/test environments preserve existing behavior. SaaS
# deployments can set them explicitly to false while keeping the platform enabled.
def _optional_ai_bool(name):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.lower() in {"1", "true", "yes", "on"}


AI_COMPANY_DEFAULT_ENABLED = _optional_ai_bool("AI_COMPANY_DEFAULT_ENABLED")
AI_COMPANY_DEFAULT_EXTERNAL_COMMITS = _optional_ai_bool(
    "AI_COMPANY_DEFAULT_EXTERNAL_COMMITS"
)
AI_COMPANY_DEFAULT_PRIVACY_ACKNOWLEDGED = _optional_ai_bool(
    "AI_COMPANY_DEFAULT_PRIVACY_ACKNOWLEDGED"
)
AI_COMPANY_DEFAULT_MONTHLY_REQUEST_LIMIT = int(
    os.environ.get("AI_COMPANY_DEFAULT_MONTHLY_REQUEST_LIMIT", 500)
)
AI_COMPANY_DEFAULT_RETENTION_DAYS = int(
    os.environ.get("AI_COMPANY_DEFAULT_RETENTION_DAYS", 90)
)
AI_COMPANY_DEFAULT_ACCESS_MODE = os.environ.get(
    "AI_COMPANY_DEFAULT_ACCESS_MODE", "all_users"
).strip()
AI_COMPANY_DEFAULT_FAILURE_THRESHOLD = int(
    os.environ.get("AI_COMPANY_DEFAULT_FAILURE_THRESHOLD", 5)
)
AI_COMPANY_DEFAULT_FAILURE_WINDOW_MINUTES = int(
    os.environ.get("AI_COMPANY_DEFAULT_FAILURE_WINDOW_MINUTES", 60)
)
AI_PROVIDER = os.environ.get("AI_PROVIDER", "openai")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_ORG_ID = os.environ.get("OPENAI_ORG_ID", "").strip()
OPENAI_PROJECT_ID = os.environ.get("OPENAI_PROJECT_ID", "").strip()
AI_MODEL = os.environ.get("AI_MODEL", "gpt-5")
AI_WARN_ON_UNPINNED_MODEL = os.environ.get(
    "AI_WARN_ON_UNPINNED_MODEL", "true"
).lower() in {"1", "true", "yes", "on"}
AI_ALLOWED_MODELS = [
    model.strip()
    for model in os.environ.get("AI_ALLOWED_MODELS", AI_MODEL).split(",")
    if model.strip()
]
AI_PROVIDER_TIMEOUT_SECONDS = int(os.environ.get("AI_PROVIDER_TIMEOUT_SECONDS", 30))
AI_MAX_TOOL_ROUNDS = int(os.environ.get("AI_MAX_TOOL_ROUNDS", 4))
AI_MAX_OUTPUT_TOKENS = int(os.environ.get("AI_MAX_OUTPUT_TOKENS", 3000))
AI_MAX_PROMPT_CHARS = int(os.environ.get("AI_MAX_PROMPT_CHARS", 4000))
AI_CONVERSATION_CONTEXT_TURNS = int(os.environ.get("AI_CONVERSATION_CONTEXT_TURNS", 4))
AI_CONVERSATION_CONTEXT_MINUTES = int(os.environ.get("AI_CONVERSATION_CONTEXT_MINUTES", 60))
AI_MAX_REQUEST_BYTES = int(os.environ.get("AI_MAX_REQUEST_BYTES", 12000))
AI_MAX_TOOL_OUTPUT_CHARS = int(os.environ.get("AI_MAX_TOOL_OUTPUT_CHARS", 40000))
AI_REQUIRE_EXPLICIT_WRITE_INTENT = os.environ.get(
    "AI_REQUIRE_EXPLICIT_WRITE_INTENT", "true"
).lower() in {"1", "true", "yes", "on"}
AI_RATE_LIMIT_REQUESTS = int(os.environ.get("AI_RATE_LIMIT_REQUESTS", 10))
AI_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("AI_RATE_LIMIT_WINDOW_SECONDS", 60))
AI_MONTHLY_COST_LIMIT_USD = Decimal(
    os.environ.get("AI_MONTHLY_COST_LIMIT_USD", "25.00")
)
# Configure these rates for the selected model. They are only used for the local cost guard.
AI_INPUT_COST_PER_MILLION_USD = Decimal(
    os.environ.get("AI_INPUT_COST_PER_MILLION_USD", "0")
)
AI_OUTPUT_COST_PER_MILLION_USD = Decimal(
    os.environ.get("AI_OUTPUT_COST_PER_MILLION_USD", "0")
)
AI_MODEL_PRICING_JSON = os.environ.get("AI_MODEL_PRICING_JSON", "{}")
try:
    AI_MODEL_PRICING = json.loads(AI_MODEL_PRICING_JSON)
except json.JSONDecodeError as exc:
    raise ValueError("AI_MODEL_PRICING_JSON must be valid JSON.") from exc
AI_PROACTIVE_INSIGHTS_ENABLED = os.environ.get("AI_PROACTIVE_INSIGHTS_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}
AI_PROACTIVE_MAX_ITEMS = int(os.environ.get("AI_PROACTIVE_MAX_ITEMS", 4))
AI_PROACTIVE_DISMISS_DAYS = int(os.environ.get("AI_PROACTIVE_DISMISS_DAYS", 7))
AI_PROACTIVE_REFRESH_SECONDS = int(os.environ.get("AI_PROACTIVE_REFRESH_SECONDS", 3600))
AI_STALE_LEAD_DAYS = int(os.environ.get("AI_STALE_LEAD_DAYS", 14))
AI_FORGOTTEN_TIMER_HOURS = int(os.environ.get("AI_FORGOTTEN_TIMER_HOURS", 8))
AI_DRAFT_STALE_DAYS = int(os.environ.get("AI_DRAFT_STALE_DAYS", 14))
AI_FOLLOW_UP_MIN_INTERVAL_HOURS = int(
    os.environ.get("AI_FOLLOW_UP_MIN_INTERVAL_HOURS", 24)
)
AI_READINESS_MAX_EVALUATION_AGE_DAYS = int(
    os.environ.get("AI_READINESS_MAX_EVALUATION_AGE_DAYS", 30)
)
