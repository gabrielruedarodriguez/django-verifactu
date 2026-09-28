from collections.abc import Iterator
from dataclasses import replace

from django_verifactu import conf
from django_verifactu.aeat.domain import Query, StoredRecord
from django_verifactu.aeat.query import build_query
from django_verifactu.aeat.transport import client_ssl_context, send_query


# The records the AEAT holds for a taxpayer and issue month, following every page.
def query(taxpayer_tax_id: str, *, year: int, month: int, **filters) -> Iterator[StoredRecord]:
    taxpayer = conf.taxpayer(taxpayer_tax_id)
    ssl_context = client_ssl_context(taxpayer.certificate, taxpayer.password)
    wanted = Query(taxpayer_tax_id, taxpayer.name, year=year, month=month, **filters)
    while True:
        page = send_query(
            build_query(wanted),
            ssl_context=ssl_context,
            production=conf.production(),
            seal_certificate=taxpayer.seal,
        )
        yield from page.records
        if page.next_page is None:
            return
        wanted = replace(wanted, after=page.next_page)
