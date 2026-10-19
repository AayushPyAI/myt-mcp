"""Mini-site webhook: generate the customer trip link after a quotation exists."""

from __future__ import annotations

import json

import httpx
import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.minisite.client import DEFAULT_URL, MinisiteClient, MinisiteError
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio

AUTH = "sp_sec_test_token"
TRIP_URL = "https://minisite.selectedplaces.co.il/?trip_id=1001&version=2"


def _v3(*, trip_id=1001, number="250752", version=2, quotation=True):
    trip = {"trip_id": trip_id, "number": number}
    if not quotation:
        return {"trip": trip}
    return {"trip": trip, "quotation": {"number": "10-2", "version": version, "status": "Draft",
                                        "currency": {"name": "EUR"}, "product_packages": []}}


class FakeMYT:
    def __init__(self, v3):
        self.v3 = v3

    async def get_trip_v3(self, trip_id):
        return self.v3

    async def aclose(self):
        pass


def client_for(payload=None, status=200, capture=None):
    payload = payload if payload is not None else {
        "status": "success", "code": 200, "message": "Trip link generated and processed successfully", "trip_url": TRIP_URL,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        if status != 200:
            body = payload if isinstance(payload, dict) else None
            return httpx.Response(status, json=body) if body is not None else httpx.Response(status, text=str(payload))
        return httpx.Response(200, json=payload)

    return MinisiteClient(AUTH, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_client_posts_json_and_returns_the_trip_url():
    seen = []
    data = await client_for(capture=seen).generate_trip_link(250752, 1)
    assert data["trip_url"] == TRIP_URL and data["status"] == "success"
    req = seen[0]
    assert req.method == "POST" and str(req.url) == DEFAULT_URL
    assert req.headers["content-type"].startswith("application/json")
    assert json.loads(req.content) == {"auth_code": AUTH, "trip_id": "250752", "version": "1"}


async def test_client_omits_version_when_not_given():
    seen = []
    await client_for(capture=seen).generate_trip_link(1001)
    assert b'"version"' not in seen[0].content


@pytest.mark.parametrize("status,payload,needle", [
    (401, {"status": "error", "message": "Unauthorized: Invalid or missing auth code", "trip_url": ""}, "auth code"),
    (400, {"status": "error", "message": "Please add trip id", "trip_url": ""}, "trip_id"),
    (502, {"status": "error", "message": "Error fetching data from the API", "trip_url": ""}, "ManageYourTrip"),
    (500, {"status": "error", "message": "boom", "trip_url": ""}, "500"),
])
async def test_client_maps_webhook_errors(status, payload, needle):
    with pytest.raises(MinisiteError, match=needle):
        await client_for(payload, status).generate_trip_link(1001, 1)


async def test_missing_auth_is_explained_before_any_request():
    with pytest.raises(MinisiteError, match="MINISITE_AUTH_CODE"):
        await MinisiteClient("").generate_trip_link(1)


async def call(myt, minisite=None, settings=None, **args):
    settings = settings or Settings(allowed_trip_ids=frozenset({1001}), minisite_auth_code=AUTH)
    async with Client(create_server(settings, Services(settings, myt=myt, minisite=minisite or client_for()))) as c:
        return await c.call_tool("update_minisite", args)


async def test_without_confirm_only_previews_and_hides_the_auth_code():
    minisite = client_for()
    r = await call(FakeMYT(_v3()), minisite, trip_id=1001)
    d = r.structured_content
    assert not r.is_error and d["sent"] is False and "confirm=true" in d["note"]
    assert d["trip_id"] == 1001 and d["version"] == 2 and d["trip_number"] == "250752"
    assert "auth_code" not in d and AUTH not in str(d)


async def test_with_confirm_posts_and_returns_the_customer_link():
    r = await call(FakeMYT(_v3()), trip_id=1001, confirm=True)
    d = r.structured_content
    assert not r.is_error and d["sent"] is True and d["trip_url"] == TRIP_URL and d["customer_link"] == TRIP_URL


async def test_explicit_version_overrides_the_quotation_version():
    seen = []
    r = await call(FakeMYT(_v3()), client_for(capture=seen), trip_id=1001, version="4", confirm=True)
    assert not r.is_error and r.structured_content["version"] == "4"
    assert b'"version":"4"' in seen[0].content


async def test_refuses_a_trip_with_no_quotation():
    r = await call(FakeMYT(_v3(quotation=False)), trip_id=1001)
    assert r.is_error and "no quotation yet" in r.content[0].text


async def test_refuses_a_trip_outside_the_allowed_list():
    r = await call(FakeMYT(_v3()), trip_id=5)
    assert r.is_error and "outside the allowed test trips" in r.content[0].text


def test_settings_read_minisite_from_env():
    s = Settings.from_env({"MINISITE_AUTH_CODE": "abc", "MINISITE_WEBHOOK_URL": "https://example.test/hook"})
    assert s.minisite_auth_code == "abc" and s.minisite_webhook_url == "https://example.test/hook"
