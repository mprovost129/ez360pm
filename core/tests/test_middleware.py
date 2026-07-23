from django.test import RequestFactory, SimpleTestCase

from core.middleware import RealClientIPMiddleware


class RealClientIPMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = RealClientIPMiddleware(lambda request: request)

    def test_uses_the_last_forwarded_for_hop_as_the_real_client_ip(self):
        request = self.factory.get(
            "/", HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.5"
        )

        self.middleware(request)

        self.assertEqual(request.META["REMOTE_ADDR"], "10.0.0.5")

    def test_single_hop_header_is_used_directly(self):
        request = self.factory.get("/", HTTP_X_FORWARDED_FOR="203.0.113.7")

        self.middleware(request)

        self.assertEqual(request.META["REMOTE_ADDR"], "203.0.113.7")

    def test_missing_header_leaves_remote_addr_untouched(self):
        request = self.factory.get("/")
        original = request.META["REMOTE_ADDR"]

        self.middleware(request)

        self.assertEqual(request.META["REMOTE_ADDR"], original)

    def test_blank_header_leaves_remote_addr_untouched(self):
        request = self.factory.get("/", HTTP_X_FORWARDED_FOR="")
        original = request.META["REMOTE_ADDR"]

        self.middleware(request)

        self.assertEqual(request.META["REMOTE_ADDR"], original)
