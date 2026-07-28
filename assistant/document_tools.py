from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

from documents.models import Document
from documents.proposal_services import (
    apply_retainer_credit,
    available_retainer_credit,
    create_proposal,
    create_retainer_invoice,
    sanitize_plain_text,
    sanitize_rich_text,
    save_proposal_section,
)
from documents.services import (
    attach_time_to_invoice,
    create_invoice,
    money,
    save_line_item,
)
from projects.models import Project, TimeEntry

from .draft_tracking import document_snapshot, snapshot_hash
from .models import AIActionAttempt
from .registry import RegisteredTool, registry


def _object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _nullable_string(max_length=255):
    return {"type": ["string", "null"], "maxLength": max_length}


def _nullable_number():
    return {"type": ["number", "null"], "minimum": 0}


def _money(value):
    return f"{money(value):.2f}"


def _decimal(value, label, *, allow_zero=True):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a valid number.") from exc
    if result < 0 or (not allow_zero and result <= 0):
        comparator = "greater than zero" if not allow_zero else "zero or greater"
        raise ValidationError(f"{label} must be {comparator}.")
    return result


def _parse_date(value, *, default, label):
    if value in (None, ""):
        return default
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must use YYYY-MM-DD.") from exc


def _project_link(project):
    return {
        "label": str(project),
        "url": reverse("projects:detail", kwargs={"pk": project.pk}),
    }


def _document_link(document):
    name = (
        "proposals:detail"
        if document.doc_type == Document.Type.PROPOSAL
        else "documents:invoice-detail"
    )
    return {
        "label": f"{document.get_doc_type_display()} {document.number}",
        "url": reverse(name, kwargs={"pk": document.pk}),
    }


def _resolve_project(company, reference):
    reference = reference.strip()
    projects = Project.objects.for_company(company).select_related("client")
    exact = projects.filter(number__iexact=reference).first()
    if exact:
        return exact
    matches = list(
        projects.filter(
            Q(name__iexact=reference)
            | Q(name__icontains=reference)
            | Q(client__company_name__icontains=reference)
            | Q(client__contacts__first_name__icontains=reference)
            | Q(client__contacts__last_name__icontains=reference)
        )
        .distinct()
        .order_by("-created_at", "pk")[:8]
    )
    if not matches:
        raise ValidationError("No project matched that reference.")
    if len(matches) > 1:
        choices = ", ".join(f"{item.number} — {item.name}" for item in matches)
        raise ValidationError(f"More than one project matched. Choose one: {choices}.")
    return matches[0]


def _resolve_accepted_proposal(company, reference):
    reference = reference.strip()
    proposals = Document.objects.for_company(company).filter(
        doc_type=Document.Type.PROPOSAL,
        status=Document.Status.ACCEPTED,
    ).select_related("project", "project__client")
    exact = proposals.filter(number__iexact=reference).first()
    if exact:
        return exact
    project = _resolve_project(company, reference)
    matches = list(proposals.filter(project=project).order_by("-responded_at", "-pk")[:8])
    if not matches:
        raise ValidationError("That project has no accepted proposal.")
    if len(matches) > 1:
        choices = ", ".join(item.number for item in matches)
        raise ValidationError(
            f"More than one accepted proposal matched. Choose one: {choices}."
        )
    return matches[0]


def _eligible_time(project):
    return list(
        project.time_entries.filter(
            end_time__isnull=False,
            billable=True,
            status=TimeEntry.Status.LOGGED,
            line_item__isnull=True,
        ).order_by("start_time", "pk")
    )


def _available_retainers(project):
    retainers = Document.objects.filter(
        company=project.company,
        project=project,
        doc_type=Document.Type.INVOICE,
        invoice_kind=Document.InvoiceKind.RETAINER,
        status=Document.Status.PAID,
    ).order_by("issue_date", "pk")
    return [
        (retainer, money(available_retainer_credit(retainer)))
        for retainer in retainers
        if available_retainer_credit(retainer) > 0
    ]


def _validate_sections(raw_sections):
    if not isinstance(raw_sections, list):
        raise ValidationError("Proposal sections must be a list.")
    if len(raw_sections) > 12:
        raise ValidationError("A proposal draft may contain at most 12 sections.")
    sections = []
    for index, raw in enumerate(raw_sections, start=1):
        if not isinstance(raw, dict) or set(raw) != {"heading", "body"}:
            raise ValidationError(
                f"Proposal section {index} must contain only heading and body."
            )
        heading = sanitize_plain_text(raw.get("heading", ""))[:255]
        body = sanitize_rich_text(raw.get("body", ""))
        if not heading or not body:
            raise ValidationError(f"Proposal section {index} requires a heading and body.")
        sections.append({"heading": heading, "body": body})
    return sections


def _validate_line_items(raw_lines):
    if not isinstance(raw_lines, list):
        raise ValidationError("Pricing lines must be a list.")
    if not raw_lines:
        raise ValidationError("Add at least one pricing line to the draft proposal.")
    if len(raw_lines) > 25:
        raise ValidationError("A draft may contain at most 25 pricing lines.")
    lines = []
    for index, raw in enumerate(raw_lines, start=1):
        expected = {"description", "rate", "quantity", "tax_rate"}
        if not isinstance(raw, dict) or set(raw) != expected:
            raise ValidationError(
                f"Pricing line {index} must contain description, rate, quantity, and tax_rate."
            )
        description = sanitize_plain_text(raw.get("description", ""))[:255]
        if not description:
            raise ValidationError(f"Pricing line {index} requires a description.")
        lines.append(
            {
                "description": description,
                "rate": _decimal(raw.get("rate"), f"Pricing line {index} rate"),
                "quantity": _decimal(
                    raw.get("quantity"), f"Pricing line {index} quantity", allow_zero=False
                ),
                "tax_rate": _decimal(raw.get("tax_rate"), f"Pricing line {index} tax rate"),
            }
        )
    return lines


def _line_totals(lines):
    subtotal = Decimal("0")
    tax = Decimal("0")
    for line in lines:
        line_total = money(line["rate"] * line["quantity"])
        subtotal += line_total
        tax += money(line_total * line["tax_rate"] / Decimal("100"))
    return money(subtotal), money(tax), money(subtotal + tax)


def _serialize_lines(lines):
    return [
        {
            "description": line["description"],
            "rate": str(line["rate"]),
            "quantity": str(line["quantity"]),
            "tax_rate": str(line["tax_rate"]),
        }
        for line in lines
    ]


def _deserialize_lines(lines):
    return [
        {
            "description": line["description"],
            "rate": _decimal(line["rate"], "Rate"),
            "quantity": _decimal(line["quantity"], "Quantity", allow_zero=False),
            "tax_rate": _decimal(line["tax_rate"], "Tax rate"),
        }
        for line in lines
    ]


def get_document_draft_context(context, arguments):
    project = _resolve_project(context.company, arguments["project_reference"])
    entries = _eligible_time(project)
    retainers = _available_retainers(project)
    accepted = list(
        project.documents.filter(
            doc_type=Document.Type.PROPOSAL,
            status=Document.Status.ACCEPTED,
        ).order_by("-responded_at", "-pk")
    )
    contacts = list(project.client.contacts.order_by("-is_primary", "last_name", "first_name"))
    return {
        "project": {
            "number": project.number,
            "name": project.name,
            "client": project.client.display_name,
            "status": project.get_status_display(),
            "billing_type": project.billing_type,
            "hourly_rate": str(project.hourly_rate) if project.hourly_rate is not None else None,
            "fixed_fee": str(project.fixed_fee) if project.fixed_fee is not None else None,
            "description": project.description,
            "site_address": ", ".join(
                value
                for value in (project.address_1, project.city, project.state, project.postal_code)
                if value
            ),
        },
        "company_defaults": {
            "proposal_terms": context.company.default_proposal_terms,
            "invoice_terms": context.company.default_invoice_terms,
            "invoice_due_days": context.company.default_invoice_due_days,
            "default_tax_rate": str(context.company.default_tax_rate),
            "accept_payments": context.company.accept_payments_default,
        },
        "eligible_recipients": [
            {
                "contact_id": contact.pk,
                "name": contact.get_full_name(),
                "email": contact.email,
                "is_primary": contact.is_primary,
            }
            for contact in contacts
            if contact.email
        ],
        "accepted_proposals": [
            {
                "number": proposal.number,
                "accepted_total": _money(proposal.accepted_total or proposal.total),
                "accepted_at": proposal.responded_at.isoformat() if proposal.responded_at else None,
            }
            for proposal in accepted
        ],
        "available_retainers": [
            {
                "number": retainer.number,
                "available_credit": _money(available),
            }
            for retainer, available in retainers
        ],
        "unbilled_time": [
            {
                "id": entry.pk,
                "date": timezone.localtime(entry.start_time).date().isoformat(),
                "description": entry.description or "Professional services",
                "hours": str(entry.duration_hours),
            }
            for entry in entries[:100]
        ],
        "links": [_project_link(project)],
    }


SECTION_SCHEMA = {
    "type": "array",
    "maxItems": 12,
    "items": _object_schema(
        {
            "heading": {"type": "string", "minLength": 1, "maxLength": 255},
            "body": {"type": "string", "minLength": 1, "maxLength": 12000},
        }
    ),
}

LINE_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "maxItems": 25,
    "items": _object_schema(
        {
            "description": {"type": "string", "minLength": 1, "maxLength": 255},
            "rate": {"type": "number", "minimum": 0},
            "quantity": {"type": "number", "exclusiveMinimum": 0},
            "tax_rate": {"type": "number", "minimum": 0},
        }
    ),
}


def preview_proposal_draft(context, arguments):
    project = _resolve_project(context.company, arguments["project_reference"])
    sections = _validate_sections(arguments["sections"])
    lines = _validate_line_items(arguments["line_items"])
    issue_date = _parse_date(
        arguments["issue_date"], default=timezone.localdate(), label="Issue date"
    )
    terms = (
        context.company.default_proposal_terms
        if arguments["terms"] is None
        else sanitize_rich_text(arguments["terms"])
    )
    notes = sanitize_rich_text(arguments["notes"] or "")
    subtotal, tax, total = _line_totals(lines)
    details = [
        f"Project: {project.number} — {project.name}",
        f"Client: {project.client.display_name}",
        f"Issue date: {issue_date.isoformat()}",
        f"Sections: {len(sections)}",
        f"Pricing lines: {len(lines)}",
        f"Subtotal: ${subtotal:.2f}",
        f"Tax: ${tax:.2f}",
        f"Draft total: ${total:.2f}",
        "This creates a draft only. It will not be issued or emailed.",
    ]
    return {
        "title": "Create proposal draft",
        "summary": f"Prepare an editable proposal draft for {project.number} — {project.name}.",
        "details": details,
        "confirm_label": "Create proposal draft",
        "revise_prompt": "Revise the proposal draft details before creating it.",
        "_execution_arguments": {
            "project_id": project.pk,
            "expected_project_updated_at": project.updated_at.isoformat(),
            "issue_date": issue_date.isoformat(),
            "terms": terms,
            "notes": notes,
            "sections": sections,
            "line_items": _serialize_lines(lines),
        },
    }


@transaction.atomic
def execute_proposal_draft(context, arguments):
    project = Project.objects.for_company(context.company).select_for_update().get(
        pk=arguments["project_id"]
    )
    if project.updated_at.isoformat() != arguments["expected_project_updated_at"]:
        raise ValidationError("The project changed after the AI preview. Prepare the draft again.")
    proposal = create_proposal(
        company=context.company,
        project=project,
        proposal_data={
            "number": "",
            "issue_date": date.fromisoformat(arguments["issue_date"]),
            "terms": arguments["terms"],
            "notes": arguments["notes"],
        },
    )
    for section in arguments["sections"]:
        save_proposal_section(
            proposal=proposal,
            heading=section["heading"],
            body=section["body"],
        )
    for line in _deserialize_lines(arguments["line_items"]):
        save_line_item(document=proposal, line_data=line)
    proposal.refresh_from_db()
    return {
        "message": f"Draft proposal {proposal.number} created for {project.name}.",
        "_created_document_id": proposal.pk,
        "links": [_document_link(proposal)],
        "redirect_url": f'{reverse("proposals:detail", kwargs={"pk": proposal.pk})}?ai_draft=1',
    }


def preview_retainer_invoice_draft(context, arguments):
    proposal = _resolve_accepted_proposal(context.company, arguments["proposal_reference"])
    accepted_total = money(proposal.accepted_total or proposal.total)
    value = _decimal(arguments["value"], "Retainer value", allow_zero=False)
    if arguments["mode"] == "percentage":
        if value > 100:
            raise ValidationError("Retainer percentage cannot exceed 100.")
        amount = money(accepted_total * value / Decimal("100"))
    else:
        amount = money(value)
    if amount > accepted_total:
        raise ValidationError("Retainer cannot exceed the accepted proposal total.")
    existing = (
        proposal.derived_invoices.filter(
            doc_type=Document.Type.INVOICE,
            invoice_kind=Document.InvoiceKind.RETAINER,
        )
        .exclude(status=Document.Status.VOID)
        .aggregate(value=Sum("total"))["value"]
        or Decimal("0")
    )
    if money(existing + amount) > accepted_total:
        raise ValidationError("Existing and proposed retainers would exceed the accepted total.")
    issue_date = _parse_date(
        arguments["issue_date"], default=timezone.localdate(), label="Issue date"
    )
    due_date = _parse_date(
        arguments["due_date"],
        default=issue_date + timedelta(days=context.company.default_invoice_due_days),
        label="Due date",
    )
    if due_date < issue_date:
        raise ValidationError("Due date cannot be before issue date.")
    terms = (
        context.company.default_invoice_terms
        if arguments["terms"] is None
        else sanitize_rich_text(arguments["terms"])
    )
    notes = sanitize_rich_text(arguments["notes"] or "")
    accept_payments = (
        context.company.accept_payments_default
        if arguments["accept_payments"] is None
        else arguments["accept_payments"]
    )
    return {
        "title": "Create retainer invoice draft",
        "summary": f"Prepare a retainer invoice from accepted proposal {proposal.number}.",
        "details": [
            f"Project: {proposal.project.number} — {proposal.project.name}",
            f"Client: {proposal.project.client.display_name}",
            f"Accepted proposal total: ${accepted_total:.2f}",
            f"Retainer: ${amount:.2f}",
            f"Issue date: {issue_date.isoformat()}",
            f"Due date: {due_date.isoformat()}",
            f"Online payment: {'Enabled' if accept_payments else 'Disabled'}",
            "This creates a draft only. It will not be issued or emailed.",
        ],
        "confirm_label": "Create retainer draft",
        "_execution_arguments": {
            "proposal_id": proposal.pk,
            "expected_proposal_updated_at": proposal.updated_at.isoformat(),
            "expected_accepted_total": str(accepted_total),
            "mode": arguments["mode"],
            "value": str(value),
            "invoice_data": {
                "number": "",
                "issue_date": issue_date.isoformat(),
                "due_date": due_date.isoformat(),
                "terms": terms,
                "notes": notes,
                "accept_payments": accept_payments,
            },
        },
    }


@transaction.atomic
def execute_retainer_invoice_draft(context, arguments):
    proposal = (
        Document.objects.for_company(context.company)
        .select_for_update()
        .select_related("project")
        .get(pk=arguments["proposal_id"], doc_type=Document.Type.PROPOSAL)
    )
    current_total = money(proposal.accepted_total or proposal.total)
    if (
        proposal.updated_at.isoformat() != arguments["expected_proposal_updated_at"]
        or str(current_total) != arguments["expected_accepted_total"]
    ):
        raise ValidationError("The accepted proposal changed after the AI preview.")
    raw = arguments["invoice_data"]
    invoice = create_retainer_invoice(
        proposal=proposal,
        mode=arguments["mode"],
        value=Decimal(arguments["value"]),
        invoice_data={
            "number": raw["number"],
            "issue_date": date.fromisoformat(raw["issue_date"]),
            "due_date": date.fromisoformat(raw["due_date"]),
            "terms": raw["terms"],
            "notes": raw["notes"],
            "accept_payments": raw["accept_payments"],
        },
    )
    return {
        "message": f"Draft retainer invoice {invoice.number} created.",
        "_created_document_id": invoice.pk,
        "links": [_document_link(invoice)],
        "redirect_url": f'{reverse("documents:invoice-detail", kwargs={"pk": invoice.pk})}?ai_draft=1',
    }


def _select_entries(project, include_time, entry_ids):
    if project.billing_type != Project.BillingType.HOURLY:
        return []
    if not include_time:
        raise ValidationError(
            "Hourly final-invoice drafts must include selected unbilled time. Use the normal editor for an empty invoice."
        )
    eligible = _eligible_time(project)
    by_id = {entry.pk: entry for entry in eligible}
    selected_ids = list(dict.fromkeys(entry_ids or [entry.pk for entry in eligible]))
    if not selected_ids:
        raise ValidationError("No unbilled billable time is available for this project.")
    missing = [entry_id for entry_id in selected_ids if entry_id not in by_id]
    if missing:
        raise ValidationError("One or more selected time entries are no longer unbilled and billable.")
    return [by_id[entry_id] for entry_id in selected_ids]


def _generated_time_groups(entries, grouping):
    if grouping == "individual":
        return [({entry.pk}, entry.description or "Professional services") for entry in entries]
    if grouping == "description":
        grouped = defaultdict(list)
        for entry in entries:
            grouped[entry.description.strip() or "Professional services"].append(entry)
        return [({entry.pk for entry in group}, description) for description, group in grouped.items()]
    if grouping == "combined":
        return [({entry.pk for entry in entries}, "Professional services")]
    raise ValidationError("Unknown time grouping option.")


def _validate_description_groups(raw_groups, generated):
    if not isinstance(raw_groups, list):
        raise ValidationError("Description groups must be a list.")
    if len(raw_groups) > 100:
        raise ValidationError("Too many invoice description groups were supplied.")
    allowed = {tuple(sorted(ids)): default for ids, default in generated}
    overrides = {}
    for index, raw in enumerate(raw_groups, start=1):
        if not isinstance(raw, dict) or set(raw) != {"time_entry_ids", "description"}:
            raise ValidationError(
                f"Description group {index} must contain time_entry_ids and description."
            )
        ids = raw["time_entry_ids"]
        if not isinstance(ids, list) or not ids or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in ids
        ):
            raise ValidationError(f"Description group {index} has invalid time-entry IDs.")
        key = tuple(sorted(set(ids)))
        if key not in allowed:
            raise ValidationError(
                f"Description group {index} does not match the selected time grouping."
            )
        description = sanitize_plain_text(raw.get("description", ""))[:255]
        if not description:
            raise ValidationError(f"Description group {index} requires a description.")
        if key in overrides:
            raise ValidationError("The same time group received more than one description.")
        overrides[key] = description
    return overrides


def _credit_plan(project, *, apply_credit, reference, requested_amount, charges):
    if not apply_credit or charges <= 0:
        return []
    retainers = _available_retainers(project)
    if not retainers:
        raise ValidationError("No paid retainer credit is available for this project.")
    if reference:
        matches = [item for item in retainers if item[0].number.casefold() == reference.casefold()]
        if not matches:
            raise ValidationError("That paid retainer has no available credit.")
        retainers = matches
    if requested_amount is not None and not reference:
        raise ValidationError("Choose a retainer invoice when applying a specific credit amount.")
    remaining = money(charges)
    plan = []
    for retainer, available in retainers:
        amount = (
            money(_decimal(requested_amount, "Credit amount", allow_zero=False))
            if requested_amount is not None
            else min(available, remaining)
        )
        if amount > available or amount > remaining:
            raise ValidationError("Requested credit exceeds the available retainer or invoice charges.")
        if amount > 0:
            plan.append({"retainer_id": retainer.pk, "number": retainer.number, "amount": amount})
            remaining = money(remaining - amount)
        if requested_amount is not None or remaining <= 0:
            break
    return plan


DESCRIPTION_GROUP_SCHEMA = {
    "type": "array",
    "maxItems": 100,
    "items": _object_schema(
        {
            "time_entry_ids": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "integer", "minimum": 1},
            },
            "description": {"type": "string", "minLength": 1, "maxLength": 255},
        }
    ),
}


def preview_final_invoice_draft(context, arguments):
    project = _resolve_project(context.company, arguments["project_reference"])
    issue_date = _parse_date(
        arguments["issue_date"], default=timezone.localdate(), label="Issue date"
    )
    due_date = _parse_date(
        arguments["due_date"],
        default=issue_date + timedelta(days=context.company.default_invoice_due_days),
        label="Due date",
    )
    if due_date < issue_date:
        raise ValidationError("Due date cannot be before issue date.")
    entries = _select_entries(project, arguments["include_time"], arguments["time_entry_ids"])
    generated = _generated_time_groups(entries, arguments["grouping"]) if entries else []
    overrides = _validate_description_groups(arguments["description_groups"], generated)
    final_description = sanitize_plain_text(arguments["fixed_fee_description"] or "")[:255]
    if project.billing_type == Project.BillingType.FLAT_FEE:
        charges = money(project.fixed_fee)
        if arguments["time_entry_ids"] or arguments["description_groups"]:
            raise ValidationError("Fixed-fee invoices do not attach time entries.")
    else:
        charges = money(
            sum(
                (
                    money(
                        sum(
                            (
                                entry.duration_hours
                                for entry in entries
                                if entry.pk in group_ids
                            ),
                            Decimal("0"),
                        )
                        * project.hourly_rate
                    )
                    for group_ids, _default_description in generated
                ),
                Decimal("0"),
            )
        )
        if final_description:
            raise ValidationError("Fixed-fee description only applies to fixed-fee projects.")
    credit_plan = _credit_plan(
        project,
        apply_credit=arguments["apply_retainer_credit"],
        reference=arguments["retainer_invoice_reference"],
        requested_amount=arguments["credit_amount"],
        charges=charges,
    )
    credit_total = money(sum((item["amount"] for item in credit_plan), Decimal("0")))
    total = max(money(charges - credit_total), Decimal("0.00"))
    terms = (
        context.company.default_invoice_terms
        if arguments["terms"] is None
        else sanitize_rich_text(arguments["terms"])
    )
    notes = sanitize_rich_text(arguments["notes"] or "")
    accept_payments = (
        context.company.accept_payments_default
        if arguments["accept_payments"] is None
        else arguments["accept_payments"]
    )
    details = [
        f"Project: {project.number} — {project.name}",
        f"Client: {project.client.display_name}",
        f"Billing: {project.get_billing_type_display()}",
        f"Issue date: {issue_date.isoformat()}",
        f"Due date: {due_date.isoformat()}",
        f"Charges: ${charges:.2f}",
        f"Retainer credit: ${credit_total:.2f}",
        f"Draft balance: ${total:.2f}",
        f"Online payment: {'Enabled' if accept_payments else 'Disabled'}",
    ]
    if entries:
        total_hours = sum((entry.duration_hours for entry in entries), Decimal("0"))
        details.insert(4, f"Time: {len(entries)} entries / {total_hours:.2f} hours / {arguments['grouping']} grouping")
    if overrides:
        details.append(f"AI-edited client descriptions: {len(overrides)} line(s)")
    details.append("This creates a draft only. It will not be issued or emailed.")
    return {
        "title": "Create final invoice draft",
        "summary": f"Prepare an editable final invoice draft for {project.number} — {project.name}.",
        "details": details,
        "confirm_label": "Create final invoice draft",
        "_execution_arguments": {
            "project_id": project.pk,
            "expected_project_updated_at": project.updated_at.isoformat(),
            "issue_date": issue_date.isoformat(),
            "due_date": due_date.isoformat(),
            "terms": terms,
            "notes": notes,
            "accept_payments": accept_payments,
            "grouping": arguments["grouping"],
            "time_entry_ids": [entry.pk for entry in entries],
            "description_overrides": {"|".join(map(str, key)): value for key, value in overrides.items()},
            "fixed_fee_description": final_description,
            "credit_plan": [
                {"retainer_id": item["retainer_id"], "amount": str(item["amount"])}
                for item in credit_plan
            ],
        },
    }


@transaction.atomic
def execute_final_invoice_draft(context, arguments):
    project = Project.objects.for_company(context.company).select_for_update().get(
        pk=arguments["project_id"]
    )
    if project.updated_at.isoformat() != arguments["expected_project_updated_at"]:
        raise ValidationError("The project changed after the AI preview. Prepare the invoice again.")
    invoice = create_invoice(
        company=context.company,
        project=project,
        invoice_data={
            "invoice_kind": Document.InvoiceKind.FINAL,
            "number": "",
            "issue_date": date.fromisoformat(arguments["issue_date"]),
            "due_date": date.fromisoformat(arguments["due_date"]),
            "terms": arguments["terms"],
            "notes": arguments["notes"],
            "accept_payments": arguments["accept_payments"],
        },
    )
    if project.billing_type == Project.BillingType.HOURLY:
        entries = list(
            TimeEntry.objects.filter(
                company=context.company,
                project=project,
                pk__in=arguments["time_entry_ids"],
            )
        )
        attach_time_to_invoice(invoice=invoice, entries=entries, grouping=arguments["grouping"])
        overrides = {
            tuple(sorted(int(value) for value in key.split("|"))): description
            for key, description in arguments["description_overrides"].items()
        }
        if overrides:
            for line in invoice.line_items.prefetch_related("time_entries"):
                key = tuple(sorted(line.time_entries.values_list("pk", flat=True)))
                if key in overrides:
                    save_line_item(
                        document=invoice,
                        line=line,
                        line_data={
                            "description": overrides[key],
                            "rate": line.rate,
                            "quantity": line.quantity,
                            "tax_rate": line.tax_rate,
                        },
                    )
    elif arguments["fixed_fee_description"]:
        line = invoice.line_items.first()
        save_line_item(
            document=invoice,
            line=line,
            line_data={
                "description": arguments["fixed_fee_description"],
                "rate": line.rate,
                "quantity": line.quantity,
                "tax_rate": line.tax_rate,
            },
        )
    for item in arguments["credit_plan"]:
        retainer = Document.objects.for_company(context.company).get(
            pk=item["retainer_id"],
            project=project,
            invoice_kind=Document.InvoiceKind.RETAINER,
        )
        apply_retainer_credit(
            source_invoice=retainer,
            destination_invoice=invoice,
            amount=Decimal(item["amount"]),
        )
    invoice.refresh_from_db()
    return {
        "message": f"Draft final invoice {invoice.number} created with a ${invoice.total:.2f} balance.",
        "_created_document_id": invoice.pk,
        "links": [_document_link(invoice)],
        "redirect_url": f'{reverse("documents:invoice-detail", kwargs={"pk": invoice.pk})}?ai_draft=1',
    }



def _resolve_draft_document(company, reference, *, doc_type=None):
    reference = reference.strip()
    documents = (
        Document.objects.for_company(company)
        .filter(status=Document.Status.DRAFT)
        .select_related("project", "project__client")
        .prefetch_related("line_items__time_entries")
    )
    if doc_type is not None:
        documents = documents.filter(doc_type=doc_type)
    if reference.isdigit():
        by_pk = documents.filter(pk=int(reference)).first()
        if by_pk:
            return by_pk
    exact = list(documents.filter(number__iexact=reference)[:2])
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValidationError("More than one draft has that number. Specify proposal or invoice.")
    matches = list(
        documents.filter(
            Q(number__icontains=reference)
            | Q(project__number__icontains=reference)
            | Q(project__name__icontains=reference)
            | Q(project__client__company_name__icontains=reference)
            | Q(project__client__contacts__first_name__icontains=reference)
            | Q(project__client__contacts__last_name__icontains=reference)
        )
        .distinct()
        .order_by("-updated_at", "-pk")[:8]
    )
    if not matches:
        raise ValidationError("No editable company draft matched that reference.")
    if len(matches) > 1:
        choices = ", ".join(
            f"{item.number} — {item.get_doc_type_display()} — {item.project.name}"
            for item in matches
        )
        raise ValidationError(f"More than one draft matched. Choose one: {choices}.")
    return matches[0]


def get_existing_document_draft_context(context, arguments):
    document = _resolve_draft_document(context.company, arguments["document_reference"])
    return {
        "document": {
            "number": document.number,
            "type": document.doc_type,
            "kind": document.invoice_kind or None,
            "project": f"{document.project.number} — {document.project.name}",
            "client": document.project.client.display_name,
            "issue_date": document.issue_date.isoformat() if document.issue_date else None,
            "due_date": document.due_date.isoformat() if document.due_date else None,
            "accept_payments": bool(document.accept_payments),
            "terms": document.terms,
            "notes": document.notes,
            "sections": document.body_sections if document.doc_type == Document.Type.PROPOSAL else [],
            "line_items": [
                {
                    "id": line.pk,
                    "order": line.order,
                    "description": line.description,
                    "rate": str(line.rate),
                    "quantity": str(line.quantity),
                    "tax_rate": str(line.tax_rate),
                    "line_total": _money(line.line_total),
                    "time_entry_count": line.time_entries.count(),
                }
                for line in document.line_items.all()
            ],
            "subtotal": _money(document.subtotal),
            "tax_total": _money(document.tax_total),
            "credit_total": _money(document.credit_total),
            "total": _money(document.total),
        },
        "allowed_revisions": (
            ["issue_date", "terms", "notes", "sections", "pricing_lines"]
            if document.doc_type == Document.Type.PROPOSAL
            else ["issue_date", "due_date", "terms", "notes", "accept_payments", "line_descriptions"]
        ),
        "links": [_document_link(document)],
    }


def _nullable_array(schema):
    result = dict(schema)
    result["type"] = ["array", "null"]
    return result


def _preview_value(label, before, after):
    before_display = "—" if before in (None, "") else str(before)
    after_display = "—" if after in (None, "") else str(after)
    return f"{label}: {before_display} → {after_display}"


def preview_revise_proposal_draft(context, arguments):
    proposal = _resolve_draft_document(
        context.company,
        arguments["document_reference"],
        doc_type=Document.Type.PROPOSAL,
    )
    issue_date = (
        proposal.issue_date
        if arguments["issue_date"] is None
        else _parse_date(arguments["issue_date"], default=proposal.issue_date, label="Issue date")
    )
    terms = proposal.terms if arguments["terms"] is None else sanitize_rich_text(arguments["terms"])
    notes = proposal.notes if arguments["notes"] is None else sanitize_rich_text(arguments["notes"])
    sections = None if arguments["sections"] is None else _validate_sections(arguments["sections"])
    lines = None if arguments["line_items"] is None else _validate_line_items(arguments["line_items"])

    changed = []
    details = [
        f"Proposal: {proposal.number}",
        f"Project: {proposal.project.number} — {proposal.project.name}",
        f"Client: {proposal.project.client.display_name}",
    ]
    if issue_date != proposal.issue_date:
        changed.append("issue date")
        details.append(_preview_value("Issue date", proposal.issue_date, issue_date))
    if terms != proposal.terms:
        changed.append("terms")
        details.append("Customer terms will be replaced.")
    if notes != proposal.notes:
        changed.append("internal notes")
        details.append("Internal notes will be replaced.")
    if sections is not None and sections != list(proposal.body_sections):
        changed.append("proposal sections")
        details.append(f"Proposal sections: {len(proposal.body_sections)} → {len(sections)}")
    if lines is not None:
        current_lines = list(proposal.line_items.all())
        current_signature = [
            (line.description, line.rate, line.quantity, line.tax_rate)
            for line in current_lines
        ]
        proposed_signature = [
            (line["description"], line["rate"], line["quantity"], line["tax_rate"])
            for line in lines
        ]
        if current_signature != proposed_signature:
            changed.append("pricing lines")
            _subtotal, _tax, total = _line_totals(lines)
            details.extend(
                [
                    f"Pricing lines: {len(current_lines)} → {len(lines)}",
                    f"Proposal total: ${proposal.total:.2f} → ${total:.2f}",
                ]
            )
    if not changed:
        raise ValidationError("The requested proposal revision does not change the current draft.")
    details.extend(
        [
            "This updates the editable draft only.",
            "It will not issue, email, accept, or otherwise commit the proposal.",
        ]
    )
    initial_snapshot = document_snapshot(proposal)
    return {
        "title": "Revise proposal draft",
        "summary": f"Review AI-proposed changes to draft proposal {proposal.number}.",
        "details": details,
        "confirm_label": "Apply proposal revisions",
        "revise_prompt": "Change the proposed revisions before applying them.",
        "_execution_arguments": {
            "document_id": proposal.pk,
            "expected_snapshot_hash": snapshot_hash(initial_snapshot),
            "initial_snapshot": initial_snapshot,
            "issue_date": issue_date.isoformat(),
            "terms": terms,
            "notes": notes,
            "sections": sections,
            "line_items": None if lines is None else _serialize_lines(lines),
        },
    }


@transaction.atomic
def execute_revise_proposal_draft(context, arguments):
    proposal = (
        Document.objects.for_company(context.company)
        .select_for_update()
        .get(
            pk=arguments["document_id"],
            doc_type=Document.Type.PROPOSAL,
            status=Document.Status.DRAFT,
        )
    )
    if snapshot_hash(document_snapshot(proposal)) != arguments["expected_snapshot_hash"]:
        raise ValidationError("The proposal changed after the AI preview. Review the draft again.")

    proposal.issue_date = date.fromisoformat(arguments["issue_date"])
    proposal.terms = arguments["terms"]
    proposal.notes = arguments["notes"]
    if arguments["sections"] is not None:
        proposal.body_sections = _validate_sections(arguments["sections"])
    proposal.full_clean()
    proposal.save(
        update_fields=["issue_date", "terms", "notes", "body_sections", "updated_at"]
    )

    if arguments["line_items"] is not None:
        for line in list(proposal.line_items.select_for_update().order_by("order", "pk")):
            # Proposal lines have no attached billable time, but the standard service
            # keeps totals and validation consistent with the ordinary UI.
            from documents.services import delete_line_item

            delete_line_item(line=line)
        for line in _deserialize_lines(arguments["line_items"]):
            save_line_item(document=proposal, line_data=line)

    proposal.refresh_from_db()
    return {
        "message": f"Draft proposal {proposal.number} was revised and remains unissued.",
        "_revised_document_id": proposal.pk,
        "_initial_document_snapshot": arguments["initial_snapshot"],
        "links": [_document_link(proposal)],
        "redirect_url": f'{reverse("proposals:detail", kwargs={"pk": proposal.pk})}?ai_draft=1',
    }


LINE_DESCRIPTION_SCHEMA = {
    "type": ["array", "null"],
    "maxItems": 50,
    "items": _object_schema(
        {
            "line_id": {"type": "integer", "minimum": 1},
            "description": {"type": "string", "minLength": 1, "maxLength": 255},
        }
    ),
}


def preview_revise_invoice_draft(context, arguments):
    invoice = _resolve_draft_document(
        context.company,
        arguments["document_reference"],
        doc_type=Document.Type.INVOICE,
    )
    issue_date = (
        invoice.issue_date
        if arguments["issue_date"] is None
        else _parse_date(arguments["issue_date"], default=invoice.issue_date, label="Issue date")
    )
    due_date = (
        invoice.due_date
        if arguments["due_date"] is None
        else _parse_date(arguments["due_date"], default=invoice.due_date, label="Due date")
    )
    if due_date < issue_date:
        raise ValidationError("Due date cannot be before issue date.")
    terms = invoice.terms if arguments["terms"] is None else sanitize_rich_text(arguments["terms"])
    notes = invoice.notes if arguments["notes"] is None else sanitize_rich_text(arguments["notes"])
    accept_payments = (
        invoice.accept_payments
        if arguments["accept_payments"] is None
        else bool(arguments["accept_payments"])
    )

    lines = {line.pk: line for line in invoice.line_items.all()}
    line_updates = []
    seen_ids = set()
    for item in arguments["line_descriptions"] or []:
        line_id = int(item["line_id"])
        if line_id in seen_ids:
            raise ValidationError("Each invoice line can be revised only once per request.")
        seen_ids.add(line_id)
        line = lines.get(line_id)
        if line is None:
            raise ValidationError("One or more invoice lines do not belong to this draft.")
        description = sanitize_plain_text(item["description"])[:255]
        if not description:
            raise ValidationError("Invoice line descriptions cannot be blank.")
        if description != line.description:
            line_updates.append(
                {
                    "line_id": line.pk,
                    "expected_description": line.description,
                    "description": description,
                }
            )

    details = [
        f"Invoice: {invoice.number}",
        f"Project: {invoice.project.number} — {invoice.project.name}",
        f"Client: {invoice.project.client.display_name}",
        f"Current total: ${invoice.total:.2f} (amounts will not change)",
    ]
    changed = []
    for label, before, after in (
        ("Issue date", invoice.issue_date, issue_date),
        ("Due date", invoice.due_date, due_date),
    ):
        if before != after:
            changed.append(label.lower())
            details.append(_preview_value(label, before, after))
    if terms != invoice.terms:
        changed.append("terms")
        details.append("Customer terms will be replaced.")
    if notes != invoice.notes:
        changed.append("internal notes")
        details.append("Internal notes will be replaced.")
    if accept_payments != invoice.accept_payments:
        changed.append("online payment setting")
        details.append(
            _preview_value(
                "Online payment",
                "Enabled" if invoice.accept_payments else "Disabled",
                "Enabled" if accept_payments else "Disabled",
            )
        )
    if line_updates:
        changed.append("line descriptions")
        details.append(f"Client-facing descriptions to revise: {len(line_updates)}")
        for item in line_updates[:8]:
            details.append(
                f"Line {lines[item['line_id']].order}: "
                f"{item['expected_description']} → {item['description']}"
            )
    if not changed:
        raise ValidationError("The requested invoice revision does not change the current draft.")
    details.extend(
        [
            "Rates, quantities, taxes, credits, time links, and totals will not change.",
            "This updates the editable draft only. It will not issue or email the invoice.",
        ]
    )
    initial_snapshot = document_snapshot(invoice)
    return {
        "title": "Revise invoice draft",
        "summary": f"Review AI-proposed changes to draft invoice {invoice.number}.",
        "details": details,
        "confirm_label": "Apply invoice revisions",
        "revise_prompt": "Change the proposed invoice revisions before applying them.",
        "_execution_arguments": {
            "document_id": invoice.pk,
            "expected_snapshot_hash": snapshot_hash(initial_snapshot),
            "initial_snapshot": initial_snapshot,
            "issue_date": issue_date.isoformat(),
            "due_date": due_date.isoformat(),
            "terms": terms,
            "notes": notes,
            "accept_payments": accept_payments,
            "line_updates": line_updates,
        },
    }


@transaction.atomic
def execute_revise_invoice_draft(context, arguments):
    invoice = (
        Document.objects.for_company(context.company)
        .select_for_update()
        .get(
            pk=arguments["document_id"],
            doc_type=Document.Type.INVOICE,
            status=Document.Status.DRAFT,
        )
    )
    if snapshot_hash(document_snapshot(invoice)) != arguments["expected_snapshot_hash"]:
        raise ValidationError("The invoice changed after the AI preview. Review the draft again.")

    invoice.issue_date = date.fromisoformat(arguments["issue_date"])
    invoice.due_date = date.fromisoformat(arguments["due_date"])
    invoice.terms = arguments["terms"]
    invoice.notes = arguments["notes"]
    invoice.accept_payments = arguments["accept_payments"]
    invoice.full_clean()
    invoice.save(
        update_fields=[
            "issue_date",
            "due_date",
            "terms",
            "notes",
            "accept_payments",
            "updated_at",
        ]
    )

    expected_by_id = {item["line_id"]: item for item in arguments["line_updates"]}
    if expected_by_id:
        locked_lines = {
            line.pk: line
            for line in invoice.line_items.select_for_update().filter(pk__in=expected_by_id)
        }
        if set(locked_lines) != set(expected_by_id):
            raise ValidationError("One or more invoice lines changed after the AI preview.")
        for line_id, item in expected_by_id.items():
            line = locked_lines[line_id]
            if line.description != item["expected_description"]:
                raise ValidationError("An invoice line changed after the AI preview.")
            save_line_item(
                document=invoice,
                line=line,
                line_data={
                    "description": item["description"],
                    "rate": line.rate,
                    "quantity": line.quantity,
                    "tax_rate": line.tax_rate,
                },
            )

    invoice.refresh_from_db()
    return {
        "message": f"Draft invoice {invoice.number} was revised and remains unissued.",
        "_revised_document_id": invoice.pk,
        "_initial_document_snapshot": arguments["initial_snapshot"],
        "links": [_document_link(invoice)],
        "redirect_url": f'{reverse("documents:invoice-detail", kwargs={"pk": invoice.pk})}?ai_draft=1',
    }


registry.register(
    RegisteredTool(
        "get_document_draft_context",
        "Gather company-scoped project, unbilled-time, accepted-proposal, retainer-credit, recipient, and document-default data before preparing a proposal or invoice draft.",
        _object_schema(
            {"project_reference": {"type": "string", "minLength": 1, "maxLength": 255}}
        ),
        get_document_draft_context,
    )
)
registry.register(
    RegisteredTool(
        "prepare_proposal_draft",
        "Prepare an editable proposal draft with AI-authored sections and pricing. This never issues or sends the document.",
        _object_schema(
            {
                "project_reference": {"type": "string", "minLength": 1, "maxLength": 255},
                "issue_date": _nullable_string(10),
                "terms": _nullable_string(12000),
                "notes": _nullable_string(4000),
                "sections": SECTION_SCHEMA,
                "line_items": LINE_SCHEMA,
            }
        ),
        preview_proposal_draft,
        risk_level=AIActionAttempt.RiskLevel.FINANCIAL_DRAFT,
        executor=execute_proposal_draft,
    )
)
registry.register(
    RegisteredTool(
        "prepare_retainer_invoice_draft",
        "Prepare a retainer invoice draft from an accepted proposal. This never issues or sends the invoice.",
        _object_schema(
            {
                "proposal_reference": {"type": "string", "minLength": 1, "maxLength": 255},
                "mode": {"type": "string", "enum": ["percentage", "amount"]},
                "value": {"type": "number", "exclusiveMinimum": 0},
                "issue_date": _nullable_string(10),
                "due_date": _nullable_string(10),
                "terms": _nullable_string(12000),
                "notes": _nullable_string(4000),
                "accept_payments": {"type": ["boolean", "null"]},
            }
        ),
        preview_retainer_invoice_draft,
        risk_level=AIActionAttempt.RiskLevel.FINANCIAL_DRAFT,
        executor=execute_retainer_invoice_draft,
    )
)
registry.register(
    RegisteredTool(
        "prepare_final_invoice_draft",
        "Prepare an editable final invoice draft using deterministic EZ360PM time, pricing, and retainer-credit services. This never issues or sends the invoice.",
        _object_schema(
            {
                "project_reference": {"type": "string", "minLength": 1, "maxLength": 255},
                "issue_date": _nullable_string(10),
                "due_date": _nullable_string(10),
                "terms": _nullable_string(12000),
                "notes": _nullable_string(4000),
                "accept_payments": {"type": ["boolean", "null"]},
                "include_time": {"type": "boolean"},
                "time_entry_ids": {
                    "type": "array",
                    "maxItems": 100,
                    "items": {"type": "integer", "minimum": 1},
                },
                "grouping": {"type": "string", "enum": ["individual", "description", "combined"]},
                "description_groups": DESCRIPTION_GROUP_SCHEMA,
                "fixed_fee_description": _nullable_string(255),
                "apply_retainer_credit": {"type": "boolean"},
                "retainer_invoice_reference": _nullable_string(30),
                "credit_amount": _nullable_number(),
            }
        ),
        preview_final_invoice_draft,
        risk_level=AIActionAttempt.RiskLevel.FINANCIAL_DRAFT,
        executor=execute_final_invoice_draft,
    )
)


registry.register(
    RegisteredTool(
        "get_existing_document_draft_context",
        "Read one editable proposal or invoice draft, including sections, pricing, dates, terms, and safe line identifiers, before proposing a revision.",
        _object_schema(
            {"document_reference": {"type": "string", "minLength": 1, "maxLength": 255}}
        ),
        get_existing_document_draft_context,
    )
)
registry.register(
    RegisteredTool(
        "revise_proposal_draft",
        "Revise an existing editable proposal draft after a field-level confirmation. This can replace sections and proposal pricing but never issues or sends the proposal.",
        _object_schema(
            {
                "document_reference": {"type": "string", "minLength": 1, "maxLength": 255},
                "issue_date": _nullable_string(10),
                "terms": _nullable_string(12000),
                "notes": _nullable_string(4000),
                "sections": _nullable_array(SECTION_SCHEMA),
                "line_items": _nullable_array(LINE_SCHEMA),
            }
        ),
        preview_revise_proposal_draft,
        risk_level=AIActionAttempt.RiskLevel.FINANCIAL_DRAFT,
        executor=execute_revise_proposal_draft,
    )
)
registry.register(
    RegisteredTool(
        "revise_invoice_draft",
        "Revise safe fields and client-facing descriptions on an existing editable invoice draft after confirmation. Amounts, time links, credits, and totals cannot be changed by this tool.",
        _object_schema(
            {
                "document_reference": {"type": "string", "minLength": 1, "maxLength": 255},
                "issue_date": _nullable_string(10),
                "due_date": _nullable_string(10),
                "terms": _nullable_string(12000),
                "notes": _nullable_string(4000),
                "accept_payments": {"type": ["boolean", "null"]},
                "line_descriptions": LINE_DESCRIPTION_SCHEMA,
            }
        ),
        preview_revise_invoice_draft,
        risk_level=AIActionAttempt.RiskLevel.FINANCIAL_DRAFT,
        executor=execute_revise_invoice_draft,
    )
)
