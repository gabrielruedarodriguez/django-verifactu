from collections.abc import Sequence
from typing import NamedTuple

from django_verifactu.aeat.codes import Operation, PreviousRejection


class LifecycleError(Exception):
    pass


class AlreadyRegistered(LifecycleError):
    pass


class AlreadyCancelled(LifecycleError):
    pass


class NotRegistered(LifecycleError):
    pass


class Step(NamedTuple):
    operation: str
    amendment: bool
    status: str
    error_code: int | None


_ABSENT, _REGISTERED, _CANCELLED, _EXISTS = "absent", "registered", "cancelled", "exists"


def registration_flags(history: Sequence[Step], *, amend: bool) -> dict:
    state, rejected = _replay(history)
    if state == _ABSENT:
        if not history and not amend:
            return {}
        return {"amendment": True, "previous_rejection": PreviousRejection.NOT_AT_AEAT}
    if not amend:
        raise AlreadyRegistered("the AEAT already holds this invoice: amend it instead")
    retried = rejected is not None and rejected.amendment
    return {"amendment": True, "previous_rejection": PreviousRejection.YES if retried else None}


def cancellation_flags(history: Sequence[Step]) -> dict:
    state, rejected = _replay(history)
    if state == _CANCELLED:
        raise AlreadyCancelled("the invoice is already cancelled")
    return {
        "without_previous_record": state == _ABSENT,
        "previous_rejection": rejected is not None and rejected.operation == Operation.CANCELLATION,
    }


def _replay(history: Sequence[Step]) -> tuple[str, Step | None]:
    state = _ABSENT
    for step in history:
        if step.status != "rejected":
            state = _REGISTERED if step.operation == Operation.REGISTRATION else _CANCELLED
        elif step.error_code == 3000:
            state = _EXISTS
        elif step.error_code == 3002:
            state = _ABSENT
    last = history[-1] if history else None
    return state, last if last is not None and last.status == "rejected" else None
