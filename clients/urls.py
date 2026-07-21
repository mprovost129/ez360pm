from django.urls import path

from . import views

app_name = "clients"

urlpatterns = [
    path("", views.ClientListView.as_view(), name="list"),
    path("new/", views.ClientCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ClientDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ClientUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.ClientDeleteView.as_view(), name="delete"),
    path("<int:client_pk>/contacts/new/", views.ContactCreateView.as_view(), name="contact-create"),
    path("<int:client_pk>/contacts/<int:contact_pk>/edit/", views.ContactUpdateView.as_view(), name="contact-update"),
    path("<int:client_pk>/contacts/<int:contact_pk>/delete/", views.ContactDeleteView.as_view(), name="contact-delete"),
]

