from django.urls import path

from . import delivery_views, proposal_views
from .models import Document

app_name = "proposals"

urlpatterns = [
    path("", proposal_views.ProposalListView.as_view(), name="list"),
    path("new/", proposal_views.ProposalCreateView.as_view(), name="create"),
    path("<int:pk>/", proposal_views.ProposalDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", proposal_views.ProposalUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", proposal_views.ProposalDeleteView.as_view(), name="delete"),
    path("<int:pk>/issue/", proposal_views.proposal_issue, name="issue"),
    path(
        "<int:pk>/send/",
        delivery_views.DocumentSendView.as_view(
            doc_type=Document.Type.PROPOSAL,
            success_url_name="proposals:detail",
        ),
        name="send",
    ),
    path(
        "<int:pk>/deliveries/<int:delivery_pk>/resend/",
        delivery_views.DocumentDeliveryResendView.as_view(),
        name="delivery-resend",
    ),
    path("<int:pk>/withdraw/", proposal_views.proposal_withdraw, name="withdraw"),
    path("<int:pk>/retainer/", proposal_views.RetainerCreateView.as_view(), name="retainer-create"),
    path("<int:pk>/pdf/", proposal_views.ProposalPdfView.as_view(), name="pdf"),
    path("<int:proposal_pk>/sections/new/", proposal_views.ProposalSectionView.as_view(), name="section-create"),
    path("<int:proposal_pk>/sections/<int:index>/edit/", proposal_views.ProposalSectionView.as_view(), name="section-update"),
    path("<int:proposal_pk>/sections/<int:index>/delete/", proposal_views.ProposalSectionDeleteView.as_view(), name="section-delete"),
    path("<int:proposal_pk>/sections/<int:index>/move/<str:direction>/", proposal_views.ProposalSectionMoveView.as_view(), name="section-move"),
    path("<int:proposal_pk>/prices/new/", proposal_views.ProposalLineCreateView.as_view(), name="line-create"),
    path("<int:proposal_pk>/prices/<int:line_pk>/edit/", proposal_views.ProposalLineUpdateView.as_view(), name="line-update"),
    path("<int:proposal_pk>/prices/<int:line_pk>/delete/", proposal_views.ProposalLineDeleteView.as_view(), name="line-delete"),
    path("<int:proposal_pk>/prices/<int:line_pk>/move/<str:direction>/", proposal_views.ProposalLineMoveView.as_view(), name="line-move"),
]
