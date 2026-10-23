import httpx
import pytest

from sentinel.config import Paths, load_secrets, repo_root

URL = (
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/"
    "2006q1_form345.zip"
)


@pytest.mark.network
def test_sec_archive_reachable_with_contact():
    secrets = load_secrets(Paths.from_root(repo_root()).env_file)
    resp = httpx.head(URL, headers={"User-Agent": secrets.sec_user_agent}, timeout=30)
    assert resp.status_code == 200
    assert int(resp.headers["Content-Length"]) > 1_000_000
