import lxml.html
import pytest
from django.core.management import call_command
from django.urls import reverse

from django_verifactu.models import Installation, Record, Submission
from django_verifactu.sending import send_pending
from tests.conftest import registered
from tests.shop.models import Customer, Sale

pytestmark = pytest.mark.django_db
EVIDENCE = [Installation, Record, Submission]


def url(model, view, *args):
    return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_{view}", args=args)


def form_data(page, form_id):
    return dict(lxml.html.fromstring(page.content).get_element_by_id(form_id).form_values())


@pytest.fixture
def record(aeat):
    [record] = registered("A-1")
    send_pending()
    return Record.objects.get(pk=record.pk)


def test_the_admin_passes_the_system_checks():
    call_command("check")


@pytest.mark.parametrize("model", EVIDENCE)
def test_evidence_can_be_browsed(admin_client, record, model):
    changelist = admin_client.get(url(model, "changelist"))
    page = admin_client.get(url(model, "change", model.objects.get().pk))
    assert (changelist.status_code, page.status_code) == (200, 200)
    assert b"delete_selected" not in changelist.content
    assert b'name="_save"' not in page.content


@pytest.mark.parametrize("model", EVIDENCE)
def test_evidence_cannot_be_written_from_the_admin(admin_client, record, model):
    pk = model.objects.get().pk
    assert admin_client.get(url(model, "add")).status_code == 403
    assert admin_client.post(url(model, "change", pk), {}).status_code == 403
    assert admin_client.post(url(model, "delete", pk), {"post": "yes"}).status_code == 403


def test_a_record_shows_its_xml_its_object_and_its_attempts(admin_client, record):
    page = admin_client.get(url(Record, "change", record.pk)).content.decode()
    assert f"&lt;sum1:Huella&gt;{record.fingerprint}&lt;/sum1:Huella&gt;" in page
    assert "Servicios de consultoría" in page
    assert str(record.content_object) in page
    assert str(Submission.objects.get()) in page


def test_a_submission_shows_its_lines(admin_client, record):
    page = admin_client.get(url(Submission, "change", Submission.objects.get().pk))
    assert str(record) in page.content.decode()


def test_an_invoice_shows_its_records(admin_client, record):
    page = admin_client.get(url(Sale, "change", record.object_id)).content.decode()
    assert str(record.installation) in page
    assert url(Record, "change", record.pk) in page


def test_saving_an_invoice_leaves_its_records_alone(admin_client, record):
    change = url(Sale, "change", record.object_id)
    customer = Customer.objects.create(name="Cliente")
    data = form_data(admin_client.get(change), "sale_form")
    data |= {"number": "A-1 bis", "customer": customer.pk}
    assert admin_client.post(change, data).status_code == 302
    assert Sale.objects.get().number == "A-1 bis"
    assert Record.objects.get().content_object == Sale.objects.get()


INLINE = "django_verifactu-record-content_type-object_id"


@pytest.mark.parametrize(
    "tampering",
    [
        {f"{INLINE}-0-DELETE": "on"},
        {f"{INLINE}-0-invoice_number": "B-1", f"{INLINE}-0-status": "accepted"},
        {f"{INLINE}-TOTAL_FORMS": "2", f"{INLINE}-1-invoice_number": "B-1"},
        {"_saveasnew": "Save as new"},
    ],
)
def test_the_records_inline_ignores_whatever_is_posted(admin_client, record, tampering):
    change = url(Sale, "change", record.object_id)
    customer = Customer.objects.create(name="Cliente")
    data = form_data(admin_client.get(change), "sale_form") | {"customer": customer.pk}
    before = list(Record.objects.values())
    assert admin_client.post(change, data | tampering).status_code == 302
    assert list(Record.objects.values()) == before


def test_an_invoice_with_records_cannot_be_deleted_from_the_admin(admin_client, record):
    page = admin_client.get(url(Sale, "delete", record.object_id))
    assert list(page.context["protected"])
    admin_client.post(url(Sale, "delete", record.object_id), {"post": "yes"})
    selected = {"action": "delete_selected", "_selected_action": [record.object_id], "post": "yes"}
    admin_client.post(url(Sale, "changelist"), selected)
    assert Sale.objects.exists()
