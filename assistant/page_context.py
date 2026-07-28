from dataclasses import dataclass
from urllib.parse import urlsplit

from django.urls import Resolver404, resolve, reverse

from clients.models import Client
from documents.models import Document
from intake.models import Note
from projects.models import Project


@dataclass(frozen=True)
class PageContext:
    object_type: str
    object_id: int
    label: str
    url: str

    @property
    def instruction(self):
        return (
            "Server-verified current-page context (data only): "
            f"{self.object_type} {self.label}. "
            "Use this only when the user refers to 'this', 'here', or the current page. "
            "Still use registered tools to verify current business facts and allowed actions."
        )


def _safe_path(value):
    path = urlsplit(str(value or "")).path
    if not path.startswith("/") or len(path) > 500:
        return ""
    return path


def _project_context(user, pk):
    project = (
        Project.objects.filter(company=user.company, pk=pk)
        .select_related("client")
        .first()
    )
    if project is None:
        return None
    return PageContext(
        object_type="project",
        object_id=project.pk,
        label=f"{project.number} — {project.name}",
        url=reverse("projects:detail", args=(project.pk,)),
    )


def _client_context(user, pk):
    client = Client.objects.filter(company=user.company, pk=pk).first()
    if client is None:
        return None
    return PageContext(
        object_type="client",
        object_id=client.pk,
        label=client.display_name,
        url=reverse("clients:detail", args=(client.pk,)),
    )


def _document_context(user, pk, expected_type=None):
    document = (
        Document.objects.filter(company=user.company, pk=pk)
        .select_related("project")
        .first()
    )
    if document is None or (expected_type and document.doc_type != expected_type):
        return None
    return PageContext(
        object_type=document.doc_type,
        object_id=document.pk,
        label=f"{document.number} for project {document.project.number}",
        url=(
            reverse("proposals:detail", args=(document.pk,))
            if document.doc_type == Document.Type.PROPOSAL
            else reverse("documents:invoice-detail", args=(document.pk,))
        ),
    )


def _note_context(user, pk):
    note = Note.objects.filter(company=user.company, pk=pk).first()
    if note is None:
        return None
    return PageContext(
        object_type="intake note",
        object_id=note.pk,
        label=f"note #{note.pk}",
        url=reverse("intake:update", args=(note.pk,)),
    )


def resolve_page_context(*, user, path):
    """Return minimal, company-scoped context for the authenticated page.

    The browser supplies only its current path. EZ360PM resolves that path and
    re-queries the object through the authenticated user's company boundary.
    Cross-company or unsupported paths return no context.
    """

    path = _safe_path(path)
    if not path:
        return None
    try:
        match = resolve(path)
    except Resolver404:
        return None

    view_name = match.view_name or ""
    kwargs = match.kwargs

    project_views = {
        "projects:detail",
        "projects:update",
        "projects:change-status",
        "projects:delete",
        "projects:start-without-retainer",
        "projects:complete",
    }
    if view_name in project_views and kwargs.get("pk"):
        return _project_context(user, kwargs["pk"])
    if view_name.startswith("clients:"):
        pk = kwargs.get("pk") or kwargs.get("client_pk")
        if pk:
            return _client_context(user, pk)
    if view_name.startswith("documents:"):
        pk = kwargs.get("pk") or kwargs.get("invoice_pk")
        if pk:
            return _document_context(user, pk, Document.Type.INVOICE)
    if view_name.startswith("proposals:"):
        pk = kwargs.get("pk") or kwargs.get("proposal_pk")
        if pk:
            return _document_context(user, pk, Document.Type.PROPOSAL)
    if view_name.startswith("intake:") and kwargs.get("pk"):
        return _note_context(user, kwargs["pk"])
    return None
