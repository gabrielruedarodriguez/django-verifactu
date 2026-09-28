from functools import cache
from pathlib import Path

from lxml import etree

from django_verifactu.aeat.violations import Violation

_DIR = Path(__file__).parent
_XMLDSIG_URL = "http://www.w3.org/TR/xmldsig-core/xmldsig-core-schema.xsd"


class _LocalXmldsig(etree.Resolver):
    def resolve(self, url, pubid, context):
        if url == _XMLDSIG_URL:
            return self.resolve_filename(str(_DIR / "xmldsig-core-schema.xsd"), context)
        return None


@cache
def get_schema(name: str) -> etree.XMLSchema:
    parser = etree.XMLParser(no_network=True)
    parser.resolvers.add(_LocalXmldsig())
    return etree.XMLSchema(etree.parse(str(_DIR / f"{name}.xsd"), parser))


def schema_violations(element: etree._Element, name: str) -> list[Violation]:
    schema = get_schema(name)
    violations = []
    if not schema.validate(element):
        violations += [Violation(1100, error.message) for error in schema.error_log]
    # The AEAT rejects (1100) blank values, although the XSD accepts them.
    violations += [
        Violation(1100, f"{etree.QName(leaf).localname} is blank")
        for leaf in element.iter()
        if len(leaf) == 0 and not (leaf.text or "").strip()
    ]
    return violations
