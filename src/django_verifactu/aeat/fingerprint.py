import hashlib

# The AEAT reference uses Java's String.trim(), which strips only code points <= U+0020.
_JAVA_TRIM = "".join(map(chr, range(0x21)))


def _fingerprint(fields: dict[str, str]) -> str:
    payload = "&".join(f"{label}={value.strip(_JAVA_TRIM)}" for label, value in fields.items())
    return hashlib.sha256(payload.encode()).hexdigest().upper()


def registration_fingerprint(
    *,
    issuer_tax_id: str,
    invoice_number: str,
    issue_date: str,
    invoice_type: str,
    total_tax: str,
    total_amount: str,
    previous_fingerprint: str,
    generated_at: str,
) -> str:
    return _fingerprint(
        {
            "IDEmisorFactura": issuer_tax_id,
            "NumSerieFactura": invoice_number,
            "FechaExpedicionFactura": issue_date,
            "TipoFactura": invoice_type,
            "CuotaTotal": total_tax,
            "ImporteTotal": total_amount,
            "Huella": previous_fingerprint,
            "FechaHoraHusoGenRegistro": generated_at,
        }
    )


def cancellation_fingerprint(
    *,
    issuer_tax_id: str,
    invoice_number: str,
    issue_date: str,
    previous_fingerprint: str,
    generated_at: str,
) -> str:
    return _fingerprint(
        {
            "IDEmisorFacturaAnulada": issuer_tax_id,
            "NumSerieFacturaAnulada": invoice_number,
            "FechaExpedicionFacturaAnulada": issue_date,
            "Huella": previous_fingerprint,
            "FechaHoraHusoGenRegistro": generated_at,
        }
    )
