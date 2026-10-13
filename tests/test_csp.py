"""Content Security Policy of the SPA (plan §4.1) on Django 6.1's native CSP middleware.

Production: nonce + 'strict-dynamic' + Trusted Types, nothing from a CDN, and
`connect-src ipc: http://ipc.localhost` or the Tauri app loses its hardware with no visible error.
DEBUG only widens connect/style/font/img to the Vite dev server; the HMR client enters by nonce.
"""

import logging
import re

import pytest
from django.test import Client
from django.utils.csp import CSP

from live import csp

VITE = "http://localhost:5173"
WIDENED = ("connect-src", "style-src", "font-src", "img-src")


class TestBasePolicy:
    def test_is_the_production_policy(self):
        assert csp.base_policy() == {
            "default-src": [CSP.SELF],
            "script-src": [CSP.SELF, CSP.NONCE, CSP.STRICT_DYNAMIC],
            "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
            "img-src": [CSP.SELF, "data:", "blob:"],
            "font-src": [CSP.SELF, "data:"],
            "connect-src": [CSP.SELF, "ipc:", "http://ipc.localhost"],
            "frame-ancestors": [CSP.NONE],
            "base-uri": [CSP.SELF],
            "form-action": [CSP.SELF],
            "object-src": [CSP.NONE],
            "require-trusted-types-for": ["'script'"],
            "trusted-types": ["default", "vue", "'allow-duplicates'"],
            "report-uri": ["/csp-report/"],
        }

    def test_scripts_need_the_nonce_and_strict_dynamic(self):
        script_src = csp.base_policy()["script-src"]

        assert CSP.NONCE in script_src
        assert CSP.STRICT_DYNAMIC in script_src
        assert CSP.UNSAFE_INLINE not in script_src
        assert CSP.UNSAFE_EVAL not in script_src

    def test_the_tauri_bridge_can_connect(self):
        assert {"ipc:", "http://ipc.localhost"} <= set(csp.base_policy()["connect-src"])

    def test_trusted_types_are_enforced(self):
        policy = csp.base_policy()

        assert policy["require-trusted-types-for"] == ["'script'"]
        assert "*" not in policy["trusted-types"]

    def test_only_our_trusted_types_policies_are_allowed(self):
        """The page's `default` and Vue's `vue`; Lit (`lit-html`) left with OutfitKit."""
        assert csp.base_policy()["trusted-types"] == [
            "default",
            "vue",
            "'allow-duplicates'",
        ]

    def test_nothing_comes_from_another_host(self):
        """No CDN: the only URL with a host is the Tauri bridge."""
        hosts = [
            value
            for values in csp.base_policy().values()
            for value in values
            if "://" in value or value in ("https:", "http:", "*")
        ]

        assert hosts == ["http://ipc.localhost"]

    def test_the_report_uri_can_change_or_go(self):
        assert csp.base_policy(report_uri="/r/")["report-uri"] == ["/r/"]
        assert "report-uri" not in csp.base_policy(report_uri=None)

    def test_every_call_returns_a_fresh_policy(self):
        first = csp.base_policy()
        first["script-src"].append("https://evil.example")

        assert "https://evil.example" not in csp.base_policy()["script-src"]


class TestDebugPolicy:
    def test_only_connect_style_font_and_img_reach_the_dev_server(self):
        base, debug = csp.base_policy(), csp.debug_policy()

        for directive, values in debug.items():
            if directive in WIDENED:
                assert values[: len(base[directive])] == base[directive]
                assert VITE in values
            else:
                assert values == base[directive], directive
                assert not any("localhost:5173" in value for value in values), directive

    def test_the_hmr_websocket_can_connect(self):
        assert csp.debug_policy()["connect-src"] == [
            CSP.SELF,
            "ipc:",
            "http://ipc.localhost",
            VITE,
            "ws://localhost:5173",
        ]

    def test_scripts_are_unchanged(self):
        """'strict-dynamic' ignores host sources: the HMR client enters by nonce."""
        assert csp.debug_policy()["script-src"] == csp.base_policy()["script-src"]

    def test_trusted_types_are_not_enforced_for_the_vite_overlay(self):
        assert "require-trusted-types-for" not in csp.debug_policy()

    def test_a_secure_dev_server_gets_a_wss_socket(self):
        connect = csp.debug_policy("https://vite.test:5174")["connect-src"]

        assert connect[-2:] == ["https://vite.test:5174", "wss://vite.test:5174"]


class TestPolicyHeader:
    def test_renders_with_the_nonce(self):
        header = csp.policy_header(csp.base_policy(), nonce="abc123")

        assert "script-src 'self' 'nonce-abc123' 'strict-dynamic'" in header
        assert "connect-src 'self' ipc: http://ipc.localhost" in header
        assert "require-trusted-types-for 'script'" in header
        assert "trusted-types default vue 'allow-duplicates'" in header
        assert "frame-ancestors 'none'" in header
        assert "object-src 'none'" in header
        assert "report-uri /csp-report/" in header

    def test_without_a_nonce_the_placeholder_is_dropped(self):
        header = csp.policy_header(csp.base_policy())

        assert "script-src 'self' 'strict-dynamic'" in header
        assert "CSP_NONCE" not in header


class TestMiddleware:
    def test_the_suite_runs_under_the_production_policy(self, settings):
        assert settings.SECURE_CSP == csp.base_policy()
        assert (
            "django.middleware.csp.ContentSecurityPolicyMiddleware"
            in settings.MIDDLEWARE
        )

    def test_a_response_carries_the_policy_with_the_request_nonce(self, client):
        response = client.get("/csp-probe/")

        nonces = re.findall(
            r"'nonce-([^']+)'", response.headers["Content-Security-Policy"]
        )
        assert nonces == [response.content.decode()]
        assert response.headers["Content-Security-Policy"] == csp.policy_header(
            csp.base_policy(), nonce=nonces[0]
        )


class TestReportEndpoint:
    REPORT = {
        "csp-report": {
            "document-uri": "https://a.erplora.com/demo/items",
            "violated-directive": "script-src-elem",
            "blocked-uri": "https://cdn.example/x.js",
        }
    }

    def test_a_report_is_logged_and_answered_with_204(self, caplog):
        import json

        client = Client(enforce_csrf_checks=True)
        with caplog.at_level(logging.WARNING, logger="live.csp"):
            response = client.post(
                "/csp-report/",
                json.dumps(self.REPORT),
                content_type="application/csp-report",
            )

        assert response.status_code == 204
        [record] = [r for r in caplog.records if r.name == "live.csp"]
        assert record.levelno == logging.WARNING
        assert record.getMessage().startswith("csp.violation ")
        assert "https://cdn.example/x.js" in record.getMessage()

    def test_a_reporting_api_batch_is_accepted(self, client):
        import json

        body = json.dumps([{"type": "csp-violation", "body": {"blockedURL": "inline"}}])

        assert (
            client.post(
                "/csp-report/", body, content_type="application/reports+json"
            ).status_code
            == 204
        )

    def test_the_logged_report_is_truncated_to_8_kb(self, client, caplog):
        import json

        report = {"csp-report": {"script-sample": "x" * 20_000}}
        with caplog.at_level(logging.WARNING, logger="live.csp"):
            client.post(
                "/csp-report/",
                json.dumps(report),
                content_type="application/csp-report",
            )

        [record] = [r for r in caplog.records if r.name == "live.csp"]
        assert len(record.getMessage()) <= len("csp.violation ") + 8 * 1024

    @pytest.mark.parametrize("body", [b"", b"{not json", b"\xff\xfe"])
    def test_garbage_is_a_400(self, client, caplog, body):
        with caplog.at_level(logging.WARNING, logger="live.csp"):
            response = client.post(
                "/csp-report/", body, content_type="application/csp-report"
            )

        assert response.status_code == 400
        assert not [
            r
            for r in caplog.records
            if r.name == "live.csp" and r.levelno >= logging.WARNING
        ]

    def test_only_post_is_allowed(self, client):
        assert client.get("/csp-report/").status_code == 405
