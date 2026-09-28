import pytest

from django_verifactu.aeat.codes import Operation, PreviousRejection
from django_verifactu.lifecycle import (
    AlreadyCancelled,
    AlreadyRegistered,
    Step,
    cancellation_flags,
    registration_flags,
)

ALTA, ANULACION = Operation.REGISTRATION, Operation.CANCELLATION
NOT_AT_AEAT, YES = PreviousRejection.NOT_AT_AEAT, PreviousRejection.YES


def alta(status="accepted", code=None, amendment=False):
    return Step(ALTA, amendment, status, code)


def anulacion(status="accepted", code=None):
    return Step(ANULACION, False, status, code)


REJECTED = alta("rejected", 1100)
REJECTED_AMENDMENT = alta("rejected", 1100, amendment=True)


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ([], {}),
        ([REJECTED], {"amendment": True, "previous_rejection": NOT_AT_AEAT}),
        (
            [alta(), anulacion("rejected", 3002)],
            {"amendment": True, "previous_rejection": NOT_AT_AEAT},
        ),
    ],
)
def test_register(history, expected):
    assert registration_flags(history, amend=False) == expected


@pytest.mark.parametrize(
    "history", [[alta()], [alta("pending")], [alta(), anulacion()], [alta("rejected", 3000)]]
)
def test_register_refuses_an_invoice_the_aeat_holds(history):
    with pytest.raises(AlreadyRegistered):
        registration_flags(history, amend=False)


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ([], {"amendment": True, "previous_rejection": NOT_AT_AEAT}),
        ([REJECTED], {"amendment": True, "previous_rejection": NOT_AT_AEAT}),
        ([alta("accepted_with_errors", 2001)], {"amendment": True, "previous_rejection": None}),
        ([alta(), REJECTED_AMENDMENT], {"amendment": True, "previous_rejection": YES}),
        ([alta(), anulacion()], {"amendment": True, "previous_rejection": None}),
        ([alta("rejected", 3000)], {"amendment": True, "previous_rejection": None}),
        (
            [alta(amendment=True, status="rejected", code=3000), REJECTED_AMENDMENT],
            {"amendment": True, "previous_rejection": YES},
        ),
    ],
)
def test_amend(history, expected):
    assert registration_flags(history, amend=True) == expected


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ([alta()], {"without_previous_record": False, "previous_rejection": False}),
        ([alta("pending")], {"without_previous_record": False, "previous_rejection": False}),
        (
            [alta(), anulacion("rejected", 1100)],
            {"without_previous_record": False, "previous_rejection": True},
        ),
        ([], {"without_previous_record": True, "previous_rejection": False}),
        (
            [alta("rejected", 1239), anulacion("rejected", 3002)],
            {"without_previous_record": True, "previous_rejection": True},
        ),
        ([alta("rejected", 3000)], {"without_previous_record": False, "previous_rejection": False}),
    ],
)
def test_cancel(history, expected):
    assert cancellation_flags(history) == expected


def test_cancel_refuses_a_cancelled_invoice():
    with pytest.raises(AlreadyCancelled):
        cancellation_flags([alta(), anulacion("pending")])
