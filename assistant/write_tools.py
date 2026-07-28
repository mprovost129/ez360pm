import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse

from clients.models import Client, Contact
from clients.services import (
    create_client_with_primary_contact,
    save_contact,
    set_primary_contact,
    update_client,
)
from intake.models import Note
from projects.models import Project
from projects.services import create_project, update_project_details
from projects.workflow import change_project_status

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


def _normalize_phone(value):
    return re.sub(r"\D", "", value or "")


def _decimal(value, field):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a valid amount.") from exc


def _client_link(client):
    return {
        "label": client.display_name,
        "url": reverse("clients:detail", kwargs={"pk": client.pk}),
    }


def _project_link(project):
    return {
        "label": str(project),
        "url": reverse("projects:detail", kwargs={"pk": project.pk}),
    }


def _note_link(note):
    return {
        "label": f"Intake note {note.pk}",
        "url": reverse("intake:update", kwargs={"pk": note.pk}),
    }


def _resolve_client(company, reference):
    reference = reference.strip()
    clients = Client.objects.for_company(company).prefetch_related("contacts")
    if reference.isdigit():
        client = clients.filter(pk=int(reference)).first()
        if client:
            return client

    phone = _normalize_phone(reference)
    exact_matches = {}
    partial_matches = {}
    for client in clients:
        primary = client.primary_contact
        contact_match = False
        exact_contact = False
        for contact in client.contacts.all():
            searchable = " ".join(
                part
                for part in (
                    contact.first_name,
                    contact.last_name,
                    contact.email,
                    contact.phone,
                )
                if part
            )
            if reference.casefold() in searchable.casefold():
                contact_match = True
            if (contact.email and contact.email.casefold() == reference.casefold()) or (
                phone and _normalize_phone(contact.phone) == phone
            ):
                exact_contact = True

        exact_name = bool(
            client.company_name
            and client.company_name.casefold() == reference.casefold()
        )
        exact_primary = bool(
            primary and primary.get_full_name().casefold() == reference.casefold()
        )
        if exact_name or exact_primary or exact_contact:
            exact_matches[client.pk] = client
        elif reference.casefold() in client.display_name.casefold() or contact_match:
            partial_matches[client.pk] = client

    matches = list(exact_matches.values() or partial_matches.values())
    if not matches:
        raise ValidationError("No client matched that reference.")
    if len(matches) > 1:
        choices = ", ".join(
            f"{client.pk} — {client.display_name}" for client in matches[:8]
        )
        raise ValidationError(f"More than one client matched. Choose one: {choices}.")
    return matches[0]


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


def _get_contact(company, contact_id):
    contact = (
        Contact.objects.filter(client__company=company, pk=contact_id)
        .select_related("client")
        .first()
    )
    if contact is None:
        raise ValidationError("That contact was not found in this company.")
    return contact


def _get_note(company, note_id):
    note = Note.objects.for_company(company).filter(pk=note_id).first()
    if note is None:
        raise ValidationError("That intake note was not found in this company.")
    return note


def _duplicate_candidates(
    company,
    *,
    company_name="",
    email="",
    phone="",
    address_1="",
    city="",
    exclude_client_id=None,
    exclude_contact_id=None,
):
    strong = {}
    possible = {}
    email_key = (email or "").strip().casefold()
    phone_key = _normalize_phone(phone)
    contacts = Contact.objects.filter(client__company=company).select_related("client")
    if exclude_contact_id:
        contacts = contacts.exclude(pk=exclude_contact_id)
    if exclude_client_id:
        contacts = contacts.exclude(client_id=exclude_client_id)
    for contact in contacts:
        if email_key and contact.email.strip().casefold() == email_key:
            strong[contact.client_id] = contact.client
        if phone_key and _normalize_phone(contact.phone) == phone_key:
            strong[contact.client_id] = contact.client

    clients = Client.objects.for_company(company)
    if exclude_client_id:
        clients = clients.exclude(pk=exclude_client_id)
    if company_name:
        for client in clients.filter(company_name__iexact=company_name.strip()):
            possible[client.pk] = client
    if address_1 and city:
        for client in clients.filter(
            billing_address_1__iexact=address_1.strip(),
            billing_city__iexact=city.strip(),
        ):
            possible[client.pk] = client
    return list(strong.values()), list(possible.values())


def _raise_strong_duplicates(strong):
    if not strong:
        return
    choices = ", ".join(f"{client.pk} — {client.display_name}" for client in strong[:8])
    raise ValidationError(
        "A client/contact with the same email or phone already exists: "
        f"{choices}. Update or attach the existing record instead."
    )


def _client_data(arguments):
    return {
        "company_name": arguments["company_name"],
        "billing_address_1": arguments["billing_address_1"],
        "billing_address_2": arguments["billing_address_2"],
        "billing_city": arguments["billing_city"],
        "billing_state": arguments["billing_state"],
        "billing_postal_code": arguments["billing_postal_code"],
        "billing_country": arguments["billing_country"],
        "internal_note": arguments["internal_note"],
    }


def _contact_data(arguments):
    return {
        "first_name": arguments["contact_first_name"],
        "last_name": arguments["contact_last_name"],
        "email": arguments["contact_email"],
        "phone": arguments["contact_phone"],
    }


def _validate_new_client(company, client_data, contact_data):
    client = Client(company=company, **client_data)
    client.full_clean()
    contact = Contact(client=client, is_primary=True, **contact_data)
    contact.full_clean(exclude=["client"], validate_unique=False)


def _serialize(value):
    if isinstance(value, Decimal):
        return str(value)
    return value


def _diff_details(instance, changes, labels):
    details = []
    expected = {}
    for field, new_value in changes.items():
        old_value = getattr(instance, field)
        expected[field] = _serialize(old_value)
        old_display = "—" if old_value in (None, "") else str(old_value)
        new_display = "—" if new_value in (None, "") else str(new_value)
        details.append(
            f"{labels.get(field, field.replace('_', ' ').title())}: {old_display} → {new_display}"
        )
    return details, expected


def _assert_expected(instance, expected):
    changed = []
    for field, expected_value in expected.items():
        if _serialize(getattr(instance, field)) != expected_value:
            changed.append(field.replace("_", " "))
    if changed:
        raise ValidationError(
            "This record changed after the AI preview. Review it again before saving: "
            + ", ".join(changed)
            + "."
        )


CLIENT_CREATE_SCHEMA = _object_schema(
    {
        "company_name": {
            "type": "string",
            "maxLength": 255,
            "description": "Optional company or household name; use an empty string when not provided.",
        },
        "contact_first_name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 150,
            "description": "Required primary-contact first name.",
        },
        "contact_last_name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 150,
            "description": "Required primary-contact last name.",
        },
        "contact_email": {
            "type": "string",
            "maxLength": 254,
            "description": "Optional primary-contact email; use an empty string when unknown.",
        },
        "contact_phone": {
            "type": "string",
            "maxLength": 50,
            "description": "Optional primary-contact phone; use an empty string when unknown.",
        },
        "billing_address_1": {
            "type": "string",
            "maxLength": 255,
            "description": "Optional billing address line 1; use an empty string when unknown.",
        },
        "billing_address_2": {
            "type": "string",
            "maxLength": 255,
            "description": "Optional billing address line 2; use an empty string when unknown.",
        },
        "billing_city": {
            "type": "string",
            "maxLength": 100,
            "description": "Optional billing city; use an empty string when unknown.",
        },
        "billing_state": {
            "type": "string",
            "maxLength": 100,
            "description": "Optional billing state or region; use an empty string when unknown.",
        },
        "billing_postal_code": {
            "type": "string",
            "maxLength": 20,
            "description": "Optional billing postal code; use an empty string when unknown.",
        },
        "billing_country": {
            "type": "string",
            "maxLength": 100,
            "description": "Optional billing country; use an empty string when unknown.",
        },
        "internal_note": {
            "type": "string",
            "maxLength": 4000,
            "description": "Optional internal note; use an empty string when not provided.",
        },
    }
)


def preview_create_client(context, arguments):
    client_data = _client_data(arguments)
    contact_data = _contact_data(arguments)
    _validate_new_client(context.company, client_data, contact_data)
    strong, possible = _duplicate_candidates(
        context.company,
        company_name=client_data["company_name"],
        email=contact_data["email"],
        phone=contact_data["phone"],
        address_1=client_data["billing_address_1"],
        city=client_data["billing_city"],
    )
    _raise_strong_duplicates(strong)
    details = [
        f"Client: {client_data['company_name'] or contact_data['first_name'] + ' ' + contact_data['last_name']}",
        f"Primary contact: {contact_data['first_name']} {contact_data['last_name']}",
        f"Email: {contact_data['email'] or 'Not provided'}",
        f"Phone: {contact_data['phone'] or 'Not provided'}",
    ]
    if client_data["billing_address_1"]:
        details.append(
            "Billing address: "
            + ", ".join(
                part
                for part in (
                    client_data["billing_address_1"],
                    client_data["billing_city"],
                    client_data["billing_state"],
                )
                if part
            )
        )
    if possible:
        details.append(
            "Possible name/address match: "
            + ", ".join(f"{item.pk} — {item.display_name}" for item in possible[:5])
        )
    return {
        "title": "Create client",
        "summary": "Review the new client and primary contact before saving.",
        "details": details,
        "confirm_label": "Create client",
        "_execution_arguments": {
            "client_data": client_data,
            "contact_data": contact_data,
        },
    }


def execute_create_client(context, arguments):
    client_data = arguments["client_data"]
    contact_data = arguments["contact_data"]
    strong, _possible = _duplicate_candidates(
        context.company,
        company_name=client_data["company_name"],
        email=contact_data["email"],
        phone=contact_data["phone"],
        address_1=client_data["billing_address_1"],
        city=client_data["billing_city"],
    )
    _raise_strong_duplicates(strong)
    client = create_client_with_primary_contact(
        company=context.company,
        client_data=client_data,
        contact_data=contact_data,
    )
    return {
        "message": f"Client {client.display_name} created.",
        "links": [_client_link(client)],
    }


CLIENT_UPDATE_FIELDS = {
    "company_name": "Client/company name",
    "billing_address_1": "Billing address",
    "billing_address_2": "Billing address line 2",
    "billing_city": "Billing city",
    "billing_state": "Billing state",
    "billing_postal_code": "Billing postal code",
    "billing_country": "Billing country",
    "internal_note": "Internal note",
}


def preview_update_client(context, arguments):
    client = _resolve_client(context.company, arguments["client_reference"])
    changes = {
        field: arguments[field]
        for field in CLIENT_UPDATE_FIELDS
        if arguments[field] is not None
    }
    if not changes:
        raise ValidationError("No client fields were supplied to update.")
    candidate = Client.objects.get(pk=client.pk)
    for field, value in changes.items():
        setattr(candidate, field, value)
    candidate.full_clean()
    strong, possible = _duplicate_candidates(
        context.company,
        company_name=changes.get("company_name", candidate.company_name),
        address_1=changes.get("billing_address_1", candidate.billing_address_1),
        city=changes.get("billing_city", candidate.billing_city),
        exclude_client_id=client.pk,
    )
    _raise_strong_duplicates(strong)
    details, expected = _diff_details(client, changes, CLIENT_UPDATE_FIELDS)
    if possible:
        details.append(
            "Possible name/address match: "
            + ", ".join(f"{item.pk} — {item.display_name}" for item in possible[:5])
        )
    return {
        "title": "Update client",
        "summary": f"Review changes to {client.display_name}.",
        "details": details,
        "confirm_label": "Save client changes",
        "_execution_arguments": {
            "client_id": client.pk,
            "changes": changes,
            "expected": expected,
        },
    }


def execute_update_client(context, arguments):
    client = Client.objects.for_company(context.company).get(pk=arguments["client_id"])
    _assert_expected(client, arguments["expected"])
    saved = update_client(client=client, client_data=arguments["changes"])
    return {
        "message": f"Client {saved.display_name} updated.",
        "links": [_client_link(saved)],
        "refresh_page": True,
    }


CONTACT_CREATE_SCHEMA = _object_schema(
    {
        "client_reference": {"type": "string", "minLength": 1, "maxLength": 255},
        "first_name": {"type": "string", "minLength": 1, "maxLength": 150},
        "last_name": {"type": "string", "minLength": 1, "maxLength": 150},
        "email": {"type": "string", "maxLength": 254},
        "phone": {"type": "string", "maxLength": 50},
        "is_primary": {"type": "boolean"},
    }
)


def preview_add_contact(context, arguments):
    client = _resolve_client(context.company, arguments["client_reference"])
    data = {
        key: arguments[key]
        for key in ("first_name", "last_name", "email", "phone", "is_primary")
    }
    candidate = Contact(client=client, **data)
    candidate.full_clean(exclude=["client"], validate_unique=False)
    strong, _possible = _duplicate_candidates(
        context.company,
        email=data["email"],
        phone=data["phone"],
    )
    _raise_strong_duplicates(strong)
    return {
        "title": "Add contact",
        "summary": f"Add a contact to {client.display_name}.",
        "details": [
            f"Name: {data['first_name']} {data['last_name']}",
            f"Email: {data['email'] or 'Not provided'}",
            f"Phone: {data['phone'] or 'Not provided'}",
            f"Primary contact: {'Yes' if data['is_primary'] else 'No'}",
        ],
        "confirm_label": "Add contact",
        "_execution_arguments": {"client_id": client.pk, "contact_data": data},
    }


def execute_add_contact(context, arguments):
    client = Client.objects.for_company(context.company).get(pk=arguments["client_id"])
    data = arguments["contact_data"]
    strong, _possible = _duplicate_candidates(
        context.company,
        email=data["email"],
        phone=data["phone"],
    )
    _raise_strong_duplicates(strong)
    contact = save_contact(client=client, contact_data=data)
    return {
        "message": f"Contact {contact.get_full_name()} added to {client.display_name}.",
        "links": [_client_link(client)],
        "refresh_page": True,
    }


CONTACT_UPDATE_FIELDS = {
    "first_name": "First name",
    "last_name": "Last name",
    "email": "Email",
    "phone": "Phone",
    "is_primary": "Primary contact",
}


def preview_update_contact(context, arguments):
    contact = _get_contact(context.company, arguments["contact_id"])
    changes = {
        field: arguments[field]
        for field in CONTACT_UPDATE_FIELDS
        if arguments[field] is not None
    }
    if not changes:
        raise ValidationError("No contact fields were supplied to update.")
    candidate = Contact.objects.get(pk=contact.pk)
    for field, value in changes.items():
        setattr(candidate, field, value)
    candidate.full_clean(validate_constraints=False)
    strong, _possible = _duplicate_candidates(
        context.company,
        email=changes.get("email", candidate.email),
        phone=changes.get("phone", candidate.phone),
        exclude_contact_id=contact.pk,
    )
    _raise_strong_duplicates(strong)
    details, expected = _diff_details(contact, changes, CONTACT_UPDATE_FIELDS)
    return {
        "title": "Update contact",
        "summary": f"Review changes to {contact.get_full_name()} for {contact.client.display_name}.",
        "details": details,
        "confirm_label": "Save contact changes",
        "_execution_arguments": {
            "contact_id": contact.pk,
            "changes": changes,
            "expected": expected,
        },
    }


def execute_update_contact(context, arguments):
    contact = _get_contact(context.company, arguments["contact_id"])
    _assert_expected(contact, arguments["expected"])
    saved = save_contact(
        client=contact.client,
        contact=contact,
        contact_data=arguments["changes"],
    )
    return {
        "message": f"Contact {saved.get_full_name()} updated.",
        "links": [_client_link(saved.client)],
        "refresh_page": True,
    }


def preview_set_primary_contact(context, arguments):
    contact = _get_contact(context.company, arguments["contact_id"])
    if contact.is_primary:
        raise ValidationError(
            f"{contact.get_full_name()} is already the primary contact."
        )
    return {
        "title": "Change primary contact",
        "summary": f"Make {contact.get_full_name()} the primary contact for {contact.client.display_name}.",
        "details": [
            "The existing primary contact will remain on the client as a non-primary contact."
        ],
        "confirm_label": "Set primary contact",
        "_execution_arguments": {
            "contact_id": contact.pk,
            "expected_primary": False,
        },
    }


def execute_set_primary_contact(context, arguments):
    contact = _get_contact(context.company, arguments["contact_id"])
    if contact.is_primary != arguments["expected_primary"]:
        raise ValidationError("The primary-contact setting changed after the preview.")
    saved = set_primary_contact(client=contact.client, contact=contact)
    return {
        "message": f"{saved.get_full_name()} is now the primary contact.",
        "links": [_client_link(saved.client)],
        "refresh_page": True,
    }


PROJECT_CREATE_PROPERTIES = {
    "client_reference": {"type": "string", "minLength": 1, "maxLength": 255},
    "number": _nullable_string(30),
    "name": {"type": "string", "minLength": 1, "maxLength": 255},
    "description": {"type": "string", "maxLength": 4000},
    "address_1": {"type": "string", "minLength": 1, "maxLength": 255},
    "address_2": {"type": "string", "maxLength": 255},
    "city": {"type": "string", "minLength": 1, "maxLength": 100},
    "state": {"type": "string", "minLength": 1, "maxLength": 100},
    "postal_code": {"type": "string", "maxLength": 20},
    "municipality": {"type": "string", "maxLength": 100},
    "parcel_id": {"type": "string", "maxLength": 100},
    "billing_type": {"type": "string", "enum": ["hourly", "flat_fee"]},
    "hourly_rate": _nullable_number(),
    "fixed_fee": _nullable_number(),
    "estimated_hours": _nullable_number(),
}


def _project_data(arguments):
    return {
        "number": arguments["number"] or "",
        "name": arguments["name"],
        "description": arguments["description"],
        "address_1": arguments["address_1"],
        "address_2": arguments["address_2"],
        "city": arguments["city"],
        "state": arguments["state"],
        "postal_code": arguments["postal_code"],
        "municipality": arguments["municipality"],
        "parcel_id": arguments["parcel_id"],
        "billing_type": arguments["billing_type"],
        "hourly_rate": _decimal(arguments["hourly_rate"], "hourly rate"),
        "fixed_fee": _decimal(arguments["fixed_fee"], "fixed fee"),
        "estimated_hours": _decimal(arguments["estimated_hours"], "estimated hours"),
    }


def _validate_project_candidate(company, client, data, *, existing=None):
    if existing is None:
        candidate = Project(
            company=company,
            client=client,
            status=Project.Status.LEAD,
            **{**data, "number": data["number"] or "PREVIEW"},
        )
    else:
        candidate = Project.objects.get(pk=existing.pk)
        candidate.client = client
        for field, value in data.items():
            setattr(candidate, field, value)
    exclude = []
    if client.pk is None:
        exclude.append("client")
    if existing is None and not data["number"]:
        exclude.append("number")
    candidate.full_clean(exclude=exclude or None, validate_unique=False)
    return candidate


def _project_details(data, client):
    rate = (
        f"${data['hourly_rate']}/hour"
        if data["billing_type"] == Project.BillingType.HOURLY
        else f"${data['fixed_fee']} fixed fee"
    )
    return [
        f"Client: {client.display_name}",
        f"Project: {data['name']}",
        f"Number: {data['number'] or 'Auto-generated'}",
        f"Site: {data['address_1']}, {data['city']}, {data['state']}",
        f"Billing: {rate}",
        f"Estimated hours: {data['estimated_hours'] if data['estimated_hours'] is not None else 'Not provided'}",
    ]


def preview_create_project(context, arguments):
    client = _resolve_client(context.company, arguments["client_reference"])
    data = _project_data(arguments)
    _validate_project_candidate(context.company, client, data)
    return {
        "title": "Create project",
        "summary": "Create a lead project after reviewing its client, site, and billing details.",
        "details": _project_details(data, client),
        "confirm_label": "Create project",
        "_execution_arguments": {
            "client_id": client.pk,
            "project_data": {key: _serialize(value) for key, value in data.items()},
        },
    }


def _deserialize_project_data(data):
    result = dict(data)
    for field in ("hourly_rate", "fixed_fee", "estimated_hours"):
        if field in result:
            result[field] = _decimal(result[field], field.replace("_", " "))
    return result


def execute_create_project(context, arguments):
    client = Client.objects.for_company(context.company).get(pk=arguments["client_id"])
    project = create_project(
        company=context.company,
        client=client,
        project_data=_deserialize_project_data(arguments["project_data"]),
    )
    return {
        "message": f"Project {project.number} — {project.name} created.",
        "links": [_project_link(project)],
    }


PROJECT_UPDATE_FIELDS = {
    "number": "Project number",
    "name": "Project name",
    "description": "Description",
    "address_1": "Site address",
    "address_2": "Site address line 2",
    "city": "City",
    "state": "State",
    "postal_code": "Postal code",
    "municipality": "Municipality",
    "parcel_id": "Parcel ID",
    "billing_type": "Billing type",
    "hourly_rate": "Hourly rate",
    "fixed_fee": "Fixed fee",
    "estimated_hours": "Estimated hours",
}


def preview_update_project(context, arguments):
    project = _resolve_project(context.company, arguments["project_reference"])
    client = (
        _resolve_client(context.company, arguments["client_reference"])
        if arguments["client_reference"] is not None
        else project.client
    )
    changes = {}
    for field in PROJECT_UPDATE_FIELDS:
        value = arguments[field]
        if value is None:
            continue
        if field in {"hourly_rate", "fixed_fee", "estimated_hours"}:
            value = _decimal(value, field.replace("_", " "))
        changes[field] = value
    client_changed = client.pk != project.client_id
    if not changes and not client_changed:
        raise ValidationError("No project fields were supplied to update.")
    if client_changed and (
        project.status != Project.Status.LEAD
        or project.documents.exists()
        or project.time_entries.exists()
        or project.notes.exists()
    ):
        raise ValidationError(
            "A project with workflow history cannot be moved to another client."
        )

    merged = {field: getattr(project, field) for field in PROJECT_UPDATE_FIELDS}
    merged.update(changes)
    _validate_project_candidate(context.company, client, merged, existing=project)
    details, expected = _diff_details(project, changes, PROJECT_UPDATE_FIELDS)
    if client_changed:
        details.insert(
            0, f"Client: {project.client.display_name} → {client.display_name}"
        )
    return {
        "title": "Update project",
        "summary": f"Review changes to {project.number} — {project.name}.",
        "details": details,
        "confirm_label": "Save project changes",
        "_execution_arguments": {
            "project_id": project.pk,
            "client_id": client.pk,
            "changes": {key: _serialize(value) for key, value in changes.items()},
            "expected": expected,
            "expected_client_id": project.client_id,
        },
    }


def execute_update_project(context, arguments):
    project = Project.objects.for_company(context.company).get(
        pk=arguments["project_id"]
    )
    _assert_expected(project, arguments["expected"])
    if project.client_id != arguments["expected_client_id"]:
        raise ValidationError("The project client changed after the AI preview.")
    client = Client.objects.for_company(context.company).get(pk=arguments["client_id"])
    changes = _deserialize_project_data(arguments["changes"])
    saved = update_project_details(project=project, client=client, project_data=changes)
    return {
        "message": f"Project {saved.number} — {saved.name} updated.",
        "links": [_project_link(saved)],
        "refresh_page": True,
    }


def preview_change_project_status(context, arguments):
    project = _resolve_project(context.company, arguments["project_reference"])
    status = arguments["status"]
    if status == project.status:
        raise ValidationError(f"Project is already {project.get_status_display()}.")
    # The workflow service revalidates at confirmation. This preview catches
    # known errors without mutating the project.
    if status not in Project.Status.values:
        raise ValidationError("Choose a valid project status.")
    return {
        "title": "Change project status",
        "summary": f"Change {project.number} — {project.name} status.",
        "details": [
            f"Status: {project.get_status_display()} → {Project.Status(status).label}",
            "This does not alter proposals, invoices, payments, or time records.",
        ],
        "confirm_label": "Change status",
        "_execution_arguments": {
            "project_id": project.pk,
            "status": status,
            "expected_status": project.status,
            "expected_updated_at": project.updated_at.isoformat(),
        },
    }


@transaction.atomic
def execute_change_project_status(context, arguments):
    project = (
        Project.objects.select_for_update()
        .for_company(context.company)
        .get(pk=arguments["project_id"])
    )
    if project.status != arguments["expected_status"]:
        raise ValidationError("The project status changed after the AI preview.")
    if project.updated_at.isoformat() != arguments["expected_updated_at"]:
        raise ValidationError(
            "The project changed after the AI preview. Prepare a new confirmation."
        )
    saved = change_project_status(project=project, status=arguments["status"])
    return {
        "message": f"Project status changed to {saved.get_status_display()}.",
        "links": [_project_link(saved)],
        "refresh_page": True,
    }


COMBINED_INTAKE_SCHEMA = _object_schema(
    {
        "note_id": {"type": "integer", "minimum": 1},
        **CLIENT_CREATE_SCHEMA["properties"],
        **{
            key: value
            for key, value in PROJECT_CREATE_PROPERTIES.items()
            if key != "client_reference"
        },
        "archive_note": {"type": "boolean"},
    }
)


def preview_create_client_project_from_note(context, arguments):
    note = _get_note(context.company, arguments["note_id"])
    if note.project_id:
        raise ValidationError("That note is already attached to a project.")
    client_data = _client_data(arguments)
    contact_data = _contact_data(arguments)
    _validate_new_client(context.company, client_data, contact_data)
    strong, possible = _duplicate_candidates(
        context.company,
        company_name=client_data["company_name"],
        email=contact_data["email"],
        phone=contact_data["phone"],
        address_1=client_data["billing_address_1"],
        city=client_data["billing_city"],
    )
    _raise_strong_duplicates(strong)
    project_data = _project_data(arguments)
    temporary_client = Client(company=context.company, **client_data)
    if not temporary_client.company_name:
        temporary_client.company_name = (
            f"{contact_data['first_name']} {contact_data['last_name']}".strip()
        )
    _validate_project_candidate(context.company, temporary_client, project_data)
    details = [
        f"Source note: {note.body[:160]}",
        f"New client: {client_data['company_name'] or contact_data['first_name'] + ' ' + contact_data['last_name']}",
        *_project_details(project_data, temporary_client),
        f"Archive note after conversion: {'Yes' if arguments['archive_note'] else 'No'}",
    ]
    if possible:
        details.append(
            "Possible existing client match: "
            + ", ".join(f"{item.pk} — {item.display_name}" for item in possible[:5])
        )
    return {
        "title": "Create client and project from note",
        "summary": "The original intake note will be preserved and attached to the new records.",
        "details": details,
        "confirm_label": "Create client and project",
        "_execution_arguments": {
            "note_id": note.pk,
            "expected_note_updated_at": note.updated_at.isoformat(),
            "client_data": client_data,
            "contact_data": contact_data,
            "project_data": {
                key: _serialize(value) for key, value in project_data.items()
            },
            "archive_note": arguments["archive_note"],
        },
    }


@transaction.atomic
def execute_create_client_project_from_note(context, arguments):
    note = _get_note(context.company, arguments["note_id"])
    if note.updated_at.isoformat() != arguments["expected_note_updated_at"]:
        raise ValidationError("The intake note changed after the AI preview.")
    strong, _possible = _duplicate_candidates(
        context.company,
        company_name=arguments["client_data"]["company_name"],
        email=arguments["contact_data"]["email"],
        phone=arguments["contact_data"]["phone"],
        address_1=arguments["client_data"]["billing_address_1"],
        city=arguments["client_data"]["billing_city"],
    )
    _raise_strong_duplicates(strong)
    client = create_client_with_primary_contact(
        company=context.company,
        client_data=arguments["client_data"],
        contact_data=arguments["contact_data"],
    )
    project = create_project(
        company=context.company,
        client=client,
        project_data=_deserialize_project_data(arguments["project_data"]),
    )
    note.client = client
    note.project = project
    note.is_archived = arguments["archive_note"]
    note.full_clean()
    note.save(update_fields=["client", "project", "is_archived", "updated_at"])
    return {
        "message": f"Client {client.display_name} and project {project.number} created from the intake note.",
        "links": [_client_link(client), _project_link(project), _note_link(note)],
        "refresh_page": True,
    }


def preview_attach_note_to_client(context, arguments):
    note = _get_note(context.company, arguments["note_id"])
    client = _resolve_client(context.company, arguments["client_reference"])
    return {
        "title": "Attach note to client",
        "summary": f"Attach intake note {note.pk} to {client.display_name}.",
        "details": [
            f"Note: {note.body[:180]}",
            f"Archive note: {'Yes' if arguments['archive_note'] else 'No'}",
        ],
        "confirm_label": "Attach note",
        "_execution_arguments": {
            "note_id": note.pk,
            "client_id": client.pk,
            "archive_note": arguments["archive_note"],
            "expected_note_updated_at": note.updated_at.isoformat(),
        },
    }


def execute_attach_note_to_client(context, arguments):
    note = _get_note(context.company, arguments["note_id"])
    if note.updated_at.isoformat() != arguments["expected_note_updated_at"]:
        raise ValidationError("The intake note changed after the AI preview.")
    client = Client.objects.for_company(context.company).get(pk=arguments["client_id"])
    note.client = client
    note.project = None
    note.is_archived = arguments["archive_note"]
    note.full_clean()
    note.save(update_fields=["client", "project", "is_archived", "updated_at"])
    return {
        "message": f"Intake note attached to {client.display_name}.",
        "links": [_client_link(client), _note_link(note)],
        "refresh_page": True,
    }


def preview_attach_note_to_project(context, arguments):
    note = _get_note(context.company, arguments["note_id"])
    project = _resolve_project(context.company, arguments["project_reference"])
    return {
        "title": "Attach note to project",
        "summary": f"Attach intake note {note.pk} to {project.number} — {project.name}.",
        "details": [
            f"Note: {note.body[:180]}",
            f"Archive note: {'Yes' if arguments['archive_note'] else 'No'}",
        ],
        "confirm_label": "Attach note",
        "_execution_arguments": {
            "note_id": note.pk,
            "project_id": project.pk,
            "archive_note": arguments["archive_note"],
            "expected_note_updated_at": note.updated_at.isoformat(),
        },
    }


def execute_attach_note_to_project(context, arguments):
    note = _get_note(context.company, arguments["note_id"])
    if note.updated_at.isoformat() != arguments["expected_note_updated_at"]:
        raise ValidationError("The intake note changed after the AI preview.")
    project = Project.objects.for_company(context.company).get(
        pk=arguments["project_id"]
    )
    note.project = project
    note.client = project.client
    note.is_archived = arguments["archive_note"]
    note.full_clean()
    note.save(update_fields=["client", "project", "is_archived", "updated_at"])
    return {
        "message": f"Intake note attached to {project.number} — {project.name}.",
        "links": [_project_link(project), _note_link(note)],
        "refresh_page": True,
    }


registry.register(
    RegisteredTool(
        "create_client",
        "Prepare a new client and primary contact. Only contact first and last name require non-empty values; pass empty strings for other unknown fields. This tool performs its own company-scoped duplicate check for email, phone, company name, and address; do not call separate search tools first solely to check duplicates.",
        CLIENT_CREATE_SCHEMA,
        preview_create_client,
        risk_level=AIActionAttempt.RiskLevel.STRUCTURED_WRITE,
        executor=execute_create_client,
    )
)
registry.register(
    RegisteredTool(
        "update_client",
        "Prepare field-level client changes. Null means leave that field unchanged; an empty string explicitly clears a blank-allowed field.",
        _object_schema(
            {
                "client_reference": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 255,
                },
                **{
                    field: _nullable_string(4000 if field == "internal_note" else 255)
                    for field in CLIENT_UPDATE_FIELDS
                },
            }
        ),
        preview_update_client,
        risk_level=AIActionAttempt.RiskLevel.STRUCTURED_WRITE,
        executor=execute_update_client,
    )
)
registry.register(
    RegisteredTool(
        "add_contact",
        "Prepare a new contact for an existing company-scoped client.",
        CONTACT_CREATE_SCHEMA,
        preview_add_contact,
        risk_level=AIActionAttempt.RiskLevel.STRUCTURED_WRITE,
        executor=execute_add_contact,
    )
)
registry.register(
    RegisteredTool(
        "update_contact",
        "Prepare field-level changes to a contact returned by search_contacts. Null leaves a field unchanged.",
        _object_schema(
            {
                "contact_id": {"type": "integer", "minimum": 1},
                "first_name": _nullable_string(150),
                "last_name": _nullable_string(150),
                "email": _nullable_string(254),
                "phone": _nullable_string(50),
                "is_primary": {"type": ["boolean", "null"]},
            }
        ),
        preview_update_contact,
        risk_level=AIActionAttempt.RiskLevel.STRUCTURED_WRITE,
        executor=execute_update_contact,
    )
)
registry.register(
    RegisteredTool(
        "set_primary_contact",
        "Prepare making an existing company-scoped contact the primary contact for its client.",
        _object_schema({"contact_id": {"type": "integer", "minimum": 1}}),
        preview_set_primary_contact,
        risk_level=AIActionAttempt.RiskLevel.STRUCTURED_WRITE,
        executor=execute_set_primary_contact,
    )
)
registry.register(
    RegisteredTool(
        "create_project",
        "Prepare a lead project for an existing client. Money values are proposed only; EZ360PM validates and stores them deterministically.",
        _object_schema(PROJECT_CREATE_PROPERTIES),
        preview_create_project,
        risk_level=AIActionAttempt.RiskLevel.STRUCTURED_WRITE,
        executor=execute_create_project,
    )
)
registry.register(
    RegisteredTool(
        "update_project_details",
        "Prepare field-level project-detail changes. This tool cannot change project status. Null leaves a field unchanged.",
        _object_schema(
            {
                "project_reference": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 255,
                },
                "client_reference": _nullable_string(255),
                "number": _nullable_string(30),
                "name": _nullable_string(255),
                "description": _nullable_string(4000),
                "address_1": _nullable_string(255),
                "address_2": _nullable_string(255),
                "city": _nullable_string(100),
                "state": _nullable_string(100),
                "postal_code": _nullable_string(20),
                "municipality": _nullable_string(100),
                "parcel_id": _nullable_string(100),
                "billing_type": {
                    "type": ["string", "null"],
                    "enum": ["hourly", "flat_fee", None],
                },
                "hourly_rate": _nullable_number(),
                "fixed_fee": _nullable_number(),
                "estimated_hours": _nullable_number(),
            }
        ),
        preview_update_project,
        risk_level=AIActionAttempt.RiskLevel.STRUCTURED_WRITE,
        executor=execute_update_project,
    )
)
registry.register(
    RegisteredTool(
        "change_project_status",
        "Prepare a separate project-status transition through the existing workflow rules.",
        _object_schema(
            {
                "project_reference": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 255,
                },
                "status": {"type": "string", "enum": list(Project.Status.values)},
            }
        ),
        preview_change_project_status,
        risk_level=AIActionAttempt.RiskLevel.EXTERNAL_COMMIT,
        executor=execute_change_project_status,
    )
)
registry.register(
    RegisteredTool(
        "create_client_and_project_from_note",
        "Prepare a reviewed client, primary contact, and lead project from an existing intake note while preserving the note text.",
        COMBINED_INTAKE_SCHEMA,
        preview_create_client_project_from_note,
        risk_level=AIActionAttempt.RiskLevel.STRUCTURED_WRITE,
        executor=execute_create_client_project_from_note,
    )
)
registry.register(
    RegisteredTool(
        "attach_note_to_client",
        "Prepare attaching an intake note to an existing client without changing the note text.",
        _object_schema(
            {
                "note_id": {"type": "integer", "minimum": 1},
                "client_reference": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 255,
                },
                "archive_note": {"type": "boolean"},
            }
        ),
        preview_attach_note_to_client,
        risk_level=AIActionAttempt.RiskLevel.STRUCTURED_WRITE,
        executor=execute_attach_note_to_client,
    )
)
registry.register(
    RegisteredTool(
        "attach_note_to_project",
        "Prepare attaching an intake note to an existing project without changing the note text.",
        _object_schema(
            {
                "note_id": {"type": "integer", "minimum": 1},
                "project_reference": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 255,
                },
                "archive_note": {"type": "boolean"},
            }
        ),
        preview_attach_note_to_project,
        risk_level=AIActionAttempt.RiskLevel.STRUCTURED_WRITE,
        executor=execute_attach_note_to_project,
    )
)
