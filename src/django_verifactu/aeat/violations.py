from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    code: int
    message: str


class ValidationError(ValueError):
    def __init__(self, violations: list[Violation]) -> None:
        super().__init__("; ".join(f"[{v.code}] {v.message}" for v in violations))
        self.violations = violations
