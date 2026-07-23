from .forms import QuickNoteForm


def quick_note(request):
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return {}
    draft = request.session.pop("quick_note_draft", None)
    return {
        "quick_note_form": QuickNoteForm(
            draft if draft is not None else None,
            company=user.company,
        )
    }
