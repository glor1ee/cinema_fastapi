import base64

import pytest

DOCS_URLS = ["/docs", "/redoc", "/openapi.json"]


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("url", DOCS_URLS)
async def test_documentation_is_closed_to_anonymous_visitors(client, url):
    response = await client.get(url)

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("url", DOCS_URLS)
async def test_documentation_rejects_wrong_credentials(client, url):
    response = await client.get(url, headers=_basic_auth_header("docs", "wrong"))

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("url", DOCS_URLS)
async def test_documentation_opens_with_correct_credentials(client, url):
    response = await client.get(url, headers=_basic_auth_header("docs", "docs"))

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_openapi_schema_lists_every_endpoint(client):
    response = await client.get("/openapi.json", headers=_basic_auth_header("docs", "docs"))

    paths = response.json()["paths"]
    assert "/api/v1/accounts/register/" in paths
    assert "/api/v1/cinema/movies/" in paths
    assert "/api/v1/shop/cart/" in paths
    assert "/api/v1/shop/orders/" in paths


@pytest.mark.asyncio
async def test_health_endpoint_stays_public(client):
    response = await client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
