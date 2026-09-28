from django import forms
from django.contrib import admin, messages
from django.contrib.contenttypes.admin import GenericTabularInline
from django.template.response import TemplateResponse
from django.utils.html import format_html
from lxml import etree

from django_verifactu.models import Installation, Record, Submission, SubmissionLine
from django_verifactu.notices import notices


# VERI*FACTU evidence is only shown: django_verifactu writes it.
class _ViewOnly:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class _Unchanged(forms.ModelForm):
    # Before Django 5.2.13 and 6.0.4, view-only inline rows were saved with the fields they
    # do not post.
    def has_changed(self):
        return False


class RecordInline(_ViewOnly, GenericTabularInline):
    model = Record
    form = _Unchanged
    fields = [
        "installation",
        "operation",
        "amendment",
        "invoice_number",
        "issue_date",
        "generated_at",
        "status",
        "error_code",
        "error_description",
    ]
    ordering = ["installation__generation", "position"]
    show_change_link = True

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("installation")


# The notices are shown wherever the evidence is listed.
class _EvidenceAdmin(_ViewOnly, admin.ModelAdmin):
    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        # Only on a page actually shown: not after a refusal or a redirect.
        if isinstance(response, TemplateResponse):
            for notice in notices():
                messages.warning(request, notice.message)
        return response


class _LineInline(_ViewOnly, admin.TabularInline):
    model = SubmissionLine
    fields = ["status", "error_code", "error_description", "duplicate_status"]


class AttemptInline(_LineInline):
    fk_name = "record"
    fields = ["submission", *_LineInline.fields]
    verbose_name_plural = "attempts"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("submission")


class SubmissionLineInline(_LineInline):
    fk_name = "submission"
    fields = ["record", *_LineInline.fields]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("record")


@admin.register(Installation)
class InstallationAdmin(_EvidenceAdmin):
    list_display = ["taxpayer_tax_id", "production", "generation", "system_id", "created_at"]
    list_filter = ["production"]
    search_fields = ["taxpayer_tax_id", "number"]


@admin.register(Record)
class RecordAdmin(_EvidenceAdmin):
    list_display = [
        "invoice_number",
        "issue_date",
        "operation",
        "amendment",
        "status",
        "error_code",
        "installation",
        "position",
        "generated_at",
    ]
    list_filter = ["status", "operation", "installation__production"]
    list_select_related = ["installation"]
    search_fields = ["invoice_number", "installation__taxpayer_tax_id", "fingerprint"]
    exclude = ["xml"]
    readonly_fields = ["content_object", "document"]
    inlines = [AttemptInline]

    @admin.display(description="XML")
    def document(self, record):
        element = etree.fromstring(record.xml)
        pretty = etree.tostring(element, pretty_print=True, encoding="unicode")
        return format_html("<pre>{}</pre>", pretty)


@admin.register(Submission)
class SubmissionAdmin(_EvidenceAdmin):
    list_display = ["created_at", "installation", "outcome", "incident", "csv", "error_code"]
    list_filter = ["outcome", "incident", "installation__production"]
    list_select_related = ["installation"]
    search_fields = ["csv", "installation__taxpayer_tax_id"]
    exclude = ["in_flight"]
    inlines = [SubmissionLineInline]
