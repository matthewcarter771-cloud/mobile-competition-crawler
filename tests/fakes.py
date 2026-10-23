"""Minimal stand-ins for the Playwright objects the crawlers use."""

from contextlib import asynccontextmanager


class FakeRequest:
    def __init__(self, method):
        self.method = method


class FakeResponse:
    def __init__(self, url, body, status=200, method="GET"):
        self.url = url
        self.status = status
        self.ok = 200 <= status < 300
        self.request = FakeRequest(method)
        self._body = body

    async def json(self):
        return self._body


class FakeResponseInfo:
    def __init__(self, response):
        self._response = response

    @property
    def value(self):
        # Playwright's EventInfo.value is awaitable
        async def get():
            return self._response
        return get()


class FakePage:
    def __init__(self, response):
        self.response = response
        self.visited = []
        self.predicate = None

    @asynccontextmanager
    async def expect_response(self, predicate, timeout):
        self.predicate = predicate
        yield FakeResponseInfo(self.response)

    async def goto(self, url, wait_until):
        self.visited.append(url)
