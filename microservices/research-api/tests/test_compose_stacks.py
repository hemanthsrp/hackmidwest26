"""The Compose stacks run their own Postgres ("database") without TLS. The evidence
store refuses a non-local host without sslmode=require unless the service opts in with
ALLOW_INSECURE_LOCAL_DATABASE, so every service that reads it there must set the flag;
otherwise live assessments fail on that stack."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
# Python services whose database clients apply the TLS rule (decision-maker's
# require_tls, scraper-analysis's settings). The Node frontend has no such rule.
TLS_CHECKED = {"research-api", "scraper-analysis", "scraper-schema"}


def services(relative: str) -> dict[str, str]:
    path = REPO / relative
    if not path.exists():
        pytest.skip(f"{relative} is not in this checkout")
    text = path.read_text().split("\nvolumes:", 1)[0]
    blocks = re.split(r"^  ([a-z][a-z0-9-]*):\n", text, flags=re.M)[1:]
    return dict(zip(blocks[::2], blocks[1::2]))


@pytest.mark.parametrize("relative", ["compose.frontend.yml", "compose.deploy.yml"])
def test_every_service_on_the_stack_database_opts_in(relative: str) -> None:
    found = services(relative)
    assert TLS_CHECKED <= set(found), f"{relative}: expected services {sorted(TLS_CHECKED - set(found))}"
    missing = [
        name
        for name, body in found.items()
        if name in TLS_CHECKED
        and re.search(r"^\s+DATABASE_URL: postgresql://[^\n]*@database:5432/(?![^\n]*sslmode)", body, re.M)
        and 'ALLOW_INSECURE_LOCAL_DATABASE: "true"' not in body
    ]
    assert missing == [], f"{relative}: set ALLOW_INSECURE_LOCAL_DATABASE for {missing}"
