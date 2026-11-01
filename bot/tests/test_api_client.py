from __future__ import annotations

import unittest

import httpx

from app.api_client import ApiClient, EventQuery
from app.config import settings


EMPTY_PAGE = {
    "items": [],
    "is_loading": False,
    "total": 0,
    "total_regions": 0,
    "total_categories": 0,
    "page": 1,
    "page_size": 4,
    "total_pages": 1,
    "available_cities": [],
    "available_categories": [],
    "available_sources": [],
}


class ApiClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.api = ApiClient()
        await self.api._client.aclose()

    async def asyncTearDown(self) -> None:
        await self.api.close()

    def _mock(self, handler) -> None:
        self.api._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://test",
        )

    async def test_featured_query_uses_the_featured_endpoint(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=EMPTY_PAGE)

        self._mock(handler)
        page = await self.api.get_events(
            EventQuery(featured=True, date_from="2026-11-01")
        )

        self.assertEqual(page.total, 0)
        self.assertEqual(seen["path"], "/api/events/featured")
        self.assertEqual(seen["params"]["date_from"], "2026-11-01")
        self.assertNotIn("sort_by", seen["params"])

    async def test_admin_requests_send_the_admin_token(self) -> None:
        seen: dict[str, object] = {}
        original = settings.admin_token
        settings.admin_token = "test-admin-token"

        def handler(request: httpx.Request) -> httpx.Response:
            seen[f"{request.method} {request.url.path}"] = request
            if request.url.path == "/api/admin/featured" and request.method == "GET":
                return httpx.Response(200, json={"items": []})
            if request.url.path == "/api/admin/featured":
                return httpx.Response(
                    200,
                    json={
                        "item": {"id": "entry-1"},
                        "event": {"id": "event-1", "title": "Старт"},
                    },
                )
            return httpx.Response(200, json={"status": "ok"})

        try:
            self._mock(handler)
            self.assertEqual(await self.api.admin_featured(), [])
            await self.api.admin_feature_event("event-1")
            self.assertTrue(await self.api.admin_unfeature_event("entry-1"))
        finally:
            settings.admin_token = original

        for request in seen.values():
            self.assertEqual(
                request.headers["X-Admin-Token"], "test-admin-token"
            )


if __name__ == "__main__":
    unittest.main()
