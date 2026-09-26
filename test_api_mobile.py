#!/usr/bin/env python3

import unittest
from unittest.mock import Mock

from chomikuj.api_mobile import ApiMobile
from chomikuj.common_runtime import ApiCloudflareChallengeError, ChomikujError
from chomikuj.i18n import get_i18n


class ApiMobileTest(unittest.TestCase):
    def _api_with_response(self, status, body, headers=None):
        api = ApiMobile("user", "password", i18n=get_i18n("en"))
        response = Mock()
        response.status_code = status
        response.ok = 200 <= status < 400
        response.text = body
        response.headers = headers or {}
        response.json.side_effect = ValueError("not JSON")
        api.session.request = Mock(return_value=response)
        return api

    def test_cloudflare_challenge_is_reported_for_error_response(self):
        api = self._api_with_response(
            403,
            "<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x'></script></html>",
        )

        with self.assertRaisesRegex(ApiCloudflareChallengeError, "blocked by Cloudflare verification"):
            api.account_login()

    def test_cloudflare_challenge_is_reported_before_json_parsing(self):
        api = self._api_with_response(
            200,
            "<html>Verification required</html>",
            {"cf-mitigated": "challenge", "content-type": "text/html"},
        )

        with self.assertRaisesRegex(ApiCloudflareChallengeError, "blocked by Cloudflare verification"):
            api.account_login()

    def test_unrelated_invalid_json_keeps_generic_error(self):
        api = self._api_with_response(200, "not JSON: challenges.cloudflare.com", {"content-type": "application/json"})

        with self.assertRaisesRegex(ChomikujError, "Invalid JSON"):
            api.account_login()


if __name__ == "__main__":
    unittest.main()
