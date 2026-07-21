from .forms import QuickNoteForm


def quick_note(request):
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return {}
    return {"quick_note_form": QuickNoteForm(company=user.company)}

