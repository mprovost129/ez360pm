from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from projects.client_form_views import PublicProjectClientFormView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('jet/', include('jet.urls', 'jet')),  # Django JET URLS
    path('jet/dashboard/', include('jet.dashboard.urls', 'jet-dashboard')),  # Django JET dashboard URLS
    path('accounts/', include('accounts.urls')),
    path('assistant/', include('assistant.urls')),
    path('notes/', include('intake.urls')),
    path('clients/', include('clients.urls')),
    path('projects/', include('projects.urls')),
    path('f/<uuid:token>/', PublicProjectClientFormView.as_view(), name='public-project-form'),
    path('proposals/', include('documents.proposal_urls')),
    path('invoices/', include('documents.urls')),
    path('d/', include('documents.public_urls')),
    path('webhooks/', include('documents.webhook_urls')),
    path('', include('core.urls')),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [path('__debug__/', include(debug_toolbar.urls))] + urlpatterns
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
