from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('revenue/', views.RevenueView.as_view(), name='revenue'),
    path('revenue/export.csv', views.RevenueCsvView.as_view(), name='revenue-csv'),
    path('revenue/reconcile-fees/', views.RevenueFeeReconcileView.as_view(), name='revenue-reconcile-fees'),
    path('documents/drafts/', views.DraftDocumentListView.as_view(), name='draft-documents'),
    path('health/', views.HealthView.as_view(), name='health'),
]
