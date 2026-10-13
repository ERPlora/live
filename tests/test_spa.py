"""The HTML of the SPA (plan §4.2, §4.3 and §4.6).

One page for every path without a URL of its own in Django, linking the Vite build (or the dev
server with DEBUG) with the nonce of the response's CSP header. Under 'strict-dynamic' a script or
modulepreload without that nonce is a blank page.
"""

import json
import os
import re

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import Resolver404, re_path, resolve

from live import spa

#: A manifest as `vite build` writes it (`build.manifest`): the entry, two shared chunks (one
#: imported twice) and a lazily imported page. The files need not exist: the SPA only links them.
MANIFEST = {
    "frontend/main.ts": {
        "file": "assets/main-4f2a9c1b.js",
        "src": "frontend/main.ts",
        "isEntry": True,
        "imports": ["_vendor-77aa01cd.js", "_ionic-1a2b3c4d.js"],
        "dynamicImports": ["apps/demo/frontend/pages/ItemListPage.vue"],
        "css": ["assets/main-0b1c2d3e.css"],
    },
    "_vendor-77aa01cd.js": {
        "file": "assets/vendor-77aa01cd.js",
        "imports": ["_ionic-1a2b3c4d.js"],
        "css": ["assets/vendor-aa11bb22.css"],
    },
    "_ionic-1a2b3c4d.js": {"file": "assets/ionic-1a2b3c4d.js"},
    "apps/demo/frontend/pages/ItemListPage.vue": {
        "file": "assets/ItemListPage-5e6f7a8b.js",
        "src": "apps/demo/frontend/pages/ItemListPage.vue",
        "isDynamicEntry": True,
        "imports": ["_vendor-77aa01cd.js"],
        "css": ["assets/ItemListPage-c0ffee00.css"],
    },
}

SHELL = '<div id="app"></div>'
_SCRIPT_TAG = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
_PRELOAD_TAG = re.compile(r'<link\b[^>]*rel="modulepreload"[^>]*>', re.IGNORECASE)
_NONCE_ATTR = re.compile(r'\bnonce="([^"]+)"')


def write_manifest(path, manifest=MANIFEST):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest))
    return path


@pytest.fixture
def manifest_path(tmp_path, settings):
    path = write_manifest(tmp_path / "dist" / ".vite" / "manifest.json")
    settings.LIVE = {**settings.LIVE, "spa": {**settings.LIVE["spa"], "manifest": path}}
    return path


def header_nonce(response) -> str:
    nonces = re.findall(r"'nonce-([^']+)'", response.headers["Content-Security-Policy"])
    assert len(nonces) == 1, response.headers["Content-Security-Policy"]
    return nonces[0]


def json_block(html: str, element_id: str):
    found = re.search(
        rf'<script id="{element_id}" type="application/json"[^>]*>(.*?)</script>',
        html,
        re.S,
    )
    assert found, f"no JSON block {element_id!r}"
    return json.loads(found.group(1))


class TestViteManifest:
    def test_the_entry_resolves_its_chunks_and_css(self, tmp_path):
        manifest = spa.ViteManifest.load(write_manifest(tmp_path / "manifest.json"))

        assert manifest.entry("frontend/main.ts") == spa.EntryAssets(
            js="assets/main-4f2a9c1b.js",
            css=["assets/main-0b1c2d3e.css", "assets/vendor-aa11bb22.css"],
            preload=["assets/vendor-77aa01cd.js", "assets/ionic-1a2b3c4d.js"],
        )

    def test_lazy_pages_are_neither_preloaded_nor_linked(self, tmp_path):
        assets = spa.ViteManifest.load(
            write_manifest(tmp_path / "manifest.json")
        ).entry("frontend/main.ts")

        assert "assets/ItemListPage-5e6f7a8b.js" not in assets.preload
        assert "assets/ItemListPage-c0ffee00.css" not in assets.css

    def test_an_unknown_entry_is_a_configuration_error(self, tmp_path):
        manifest = spa.ViteManifest.load(write_manifest(tmp_path / "manifest.json"))

        with pytest.raises(ImproperlyConfigured, match="frontend/missing.ts"):
            manifest.entry("frontend/missing.ts")

    def test_a_missing_manifest_names_the_path_and_the_build(self, tmp_path):
        path = tmp_path / "nowhere" / "manifest.json"

        with pytest.raises(ImproperlyConfigured) as error:
            spa.ViteManifest.load(path)

        assert str(path) in str(error.value)
        assert "pnpm --filter" in str(error.value)

    def test_a_corrupt_manifest_is_a_configuration_error(self, tmp_path):
        path = tmp_path / "manifest.json"
        path.write_text("{not json")

        with pytest.raises(ImproperlyConfigured, match=re.escape(str(path))):
            spa.ViteManifest.load(path)

    def test_it_is_read_once_until_the_file_changes(self, tmp_path):
        path = write_manifest(tmp_path / "manifest.json")
        first = spa.ViteManifest.load(path)

        assert spa.ViteManifest.load(path) is first

        rebuilt = {
            **MANIFEST,
            "frontend/main.ts": {
                **MANIFEST["frontend/main.ts"],
                "file": "assets/main-new.js",
            },
        }
        write_manifest(path, rebuilt)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        assert (
            spa.ViteManifest.load(path).entry("frontend/main.ts").js
            == "assets/main-new.js"
        )


class TestAssets:
    def test_production_links_the_build_under_static_spa(self, rf, manifest_path):
        assert spa.spa_assets(rf.get("/")) == {
            "scripts": ["/static/spa/assets/main-4f2a9c1b.js"],
            "css": [
                "/static/spa/assets/main-0b1c2d3e.css",
                "/static/spa/assets/vendor-aa11bb22.css",
            ],
            "preload": [
                "/static/spa/assets/vendor-77aa01cd.js",
                "/static/spa/assets/ionic-1a2b3c4d.js",
            ],
        }

    def test_the_prefix_follows_static_url(self, rf, manifest_path, settings):
        settings.STATIC_URL = "/assets-root/"

        assert spa.spa_assets(rf.get("/"))["scripts"] == [
            "/assets-root/spa/assets/main-4f2a9c1b.js"
        ]

    def test_debug_points_to_the_dev_server_and_its_hmr_client(self, rf, settings):
        """Vite serves under its `base` ('/static/spa/') in dev too; no manifest is read."""
        settings.DEBUG = True

        assert spa.spa_assets(rf.get("/")) == {
            "scripts": [
                "http://localhost:5173/static/spa/@vite/client",
                "http://localhost:5173/static/spa/frontend/main.ts",
            ],
            "css": [],
            "preload": [],
        }

    def test_debug_without_a_dev_server_uses_the_build(
        self, rf, manifest_path, settings
    ):
        settings.DEBUG = True
        settings.LIVE = {
            **settings.LIVE,
            "spa": {**settings.LIVE["spa"], "dev_server": None},
        }

        assert spa.spa_assets(rf.get("/"))["scripts"] == [
            "/static/spa/assets/main-4f2a9c1b.js"
        ]


class TestPaletteAndConfig:
    def test_the_default_palette_without_a_cookie(self, rf):
        assert spa.palette(rf.get("/")) == "default"

    def test_a_known_palette_cookie_is_respected(self, rf):
        request = rf.get("/")
        request.COOKIES["ep_palette"] = "ocean"

        assert spa.palette(request) == "ocean"

    def test_the_old_outfitkit_cookie_is_ignored(self, rf):
        # Renamed to ep_palette in phase 1, before any real user: no fallback to the old name.
        request = rf.get("/")
        request.COOKIES["ok_palette"] = "ocean"

        assert spa.palette(request) == "default"

    @pytest.mark.parametrize("value", ["sunset", '"><script>alert(1)</script>', ""])
    def test_an_unknown_palette_falls_back_to_the_default(self, rf, value):
        request = rf.get("/")
        request.COOKIES["ep_palette"] = value

        assert spa.palette(request) == "default"

    def test_the_config_the_sdk_reads(self, rf, settings):
        settings.CSRF_COOKIE_NAME = "hub_csrftoken"
        request = rf.get("/")
        request.LANGUAGE_CODE = "es"
        request.COOKIES["ep_palette"] = "ocean"

        assert spa.spa_config(request) == {
            "csrfCookieName": "hub_csrftoken",
            "csrfHeader": "X-CSRFToken",
            "liveUrl": "/api/live",
            "apiBase": "/api",
            "lang": "es",
            "palette": "ocean",
        }

    def test_without_locale_middleware_the_language_is_the_setting(self, rf, settings):
        settings.LANGUAGE_CODE = "es"

        assert spa.spa_config(rf.get("/"))["lang"] == "es"


class TestRenderedShell:
    def test_the_shell_links_the_build(self, client, manifest_path):
        response = client.get("/spa/")
        html = response.content.decode()

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/html")
        assert SHELL in html
        assert 'src="/static/spa/assets/main-4f2a9c1b.js"' in html
        assert (
            '<link rel="stylesheet" href="/static/spa/assets/main-0b1c2d3e.css">'
            in html
        )
        assert 'href="/static/spa/assets/vendor-77aa01cd.js"' in html

    def test_every_script_and_modulepreload_carries_the_header_nonce(
        self, client, manifest_path
    ):
        response = client.get("/spa/session/")
        nonce = header_nonce(response)
        html = response.content.decode()
        tags = _SCRIPT_TAG.findall(html) + _PRELOAD_TAG.findall(html)

        assert len(_SCRIPT_TAG.findall(html)) == 3, (
            "spa-config, session-me and the entry"
        )
        assert len(_PRELOAD_TAG.findall(html)) == 2
        for tag in tags:
            found = _NONCE_ATTR.search(tag)
            assert found and found.group(1) == nonce, (
                f"tag without the response nonce: {tag}"
            )

    def test_the_entry_is_a_module_script(self, client, manifest_path):
        html = client.get("/spa/").content.decode()

        assert re.search(
            r'<script type="module" src="/static/spa/assets/main-4f2a9c1b.js" nonce="[^"]+"></script>',
            html,
        )

    def test_debug_renders_the_dev_server_scripts_with_the_nonce(
        self, client, settings
    ):
        settings.DEBUG = True
        response = client.get("/spa/")
        html = response.content.decode()
        nonce = header_nonce(response)

        for src in (
            "http://localhost:5173/static/spa/@vite/client",
            "http://localhost:5173/static/spa/frontend/main.ts",
        ):
            assert (
                f'<script type="module" src="{src}" nonce="{nonce}"></script>' in html
            )

    def test_the_html_carries_language_and_palette(
        self, client, manifest_path, settings
    ):
        settings.LANGUAGE_CODE = "es"
        client.cookies["ep_palette"] = "ocean"

        assert (
            '<html lang="es" data-ep-palette="ocean">'
            in client.get("/spa/").content.decode()
        )

    def test_an_unknown_palette_cookie_renders_the_default(self, client, manifest_path):
        client.cookies["ep_palette"] = "sunset"

        assert 'data-ep-palette="default"' in client.get("/spa/").content.decode()

    def test_the_html_ignores_the_old_outfitkit_cookie(self, client, manifest_path):
        client.cookies["ok_palette"] = "ocean"

        assert 'data-ep-palette="default"' in client.get("/spa/").content.decode()

    def test_the_html_has_no_outfitkit_attribute(self, client, manifest_path):
        assert "data-ok-" not in client.get("/spa/").content.decode()

    def test_the_spa_config_json_names_the_csrf_cookie(
        self, client, manifest_path, settings
    ):
        settings.CSRF_COOKIE_NAME = "hub_csrftoken"

        config = json_block(client.get("/spa/").content.decode(), "spa-config")

        assert config["csrfCookieName"] == "hub_csrftoken"
        assert config["liveUrl"] == "/api/live"

    def test_the_csrf_cookie_is_set_for_the_sdk(self, client, manifest_path, settings):
        settings.CSRF_COOKIE_NAME = "hub_csrftoken"

        assert "hub_csrftoken" in client.get("/spa/").cookies

    def test_extra_json_blocks_are_embedded_and_escaped(self, client, manifest_path):
        html = client.get("/spa/session/").content.decode()

        assert json_block(html, "session-me") == {
            "user": "ana",
            "note": "</script><script>alert(1)</script>",
        }
        assert "</script><script>alert(1)" not in html

    def test_extra_config_adds_project_keys_to_the_spa_config(
        self, client, manifest_path
    ):
        config = json_block(client.get("/spa/config/").content.decode(), "spa-config")

        assert config["loginUrl"] == "https://login.example.com/?hub=a"
        assert config["liveUrl"] == "/api/live"

    def test_extra_config_may_not_replace_a_key_of_the_sdk(self, client, manifest_path):
        with pytest.raises(ValueError, match="lang"):
            client.get("/spa/config-clash/")

    def test_the_viewport_and_color_scheme_metas(self, client, manifest_path):
        html = client.get("/spa/").content.decode()

        assert (
            '<meta name="viewport" content="viewport-fit=cover, width=device-width, initial-scale=1.0, '
            'minimum-scale=1.0, maximum-scale=1.0, user-scalable=no">'
        ) in html
        assert '<meta name="color-scheme" content="light dark">' in html

    def test_the_shell_is_never_cached(self, client, manifest_path):
        """A cached copy would replay a nonce."""
        assert "no-store" in client.get("/spa/").headers["Cache-Control"]

    def test_only_get_and_head_reach_the_shell(self, client, manifest_path):
        assert client.head("/spa/").status_code == 200
        assert client.post("/spa/").status_code == 405
        assert client.put("/spa/").status_code == 405

    def test_without_the_csp_middleware_the_shell_refuses_to_render(
        self, client, manifest_path, settings
    ):
        """No nonce under 'strict-dynamic' is a blank page: fail loudly instead."""
        settings.MIDDLEWARE = [
            m
            for m in settings.MIDDLEWARE
            if not m.endswith("ContentSecurityPolicyMiddleware")
        ]

        with pytest.raises(
            ImproperlyConfigured, match="ContentSecurityPolicyMiddleware"
        ):
            client.get("/spa/")

    def test_a_missing_build_is_a_configuration_error(self, client):
        with pytest.raises(ImproperlyConfigured, match="pnpm --filter"):
            client.get("/spa/")


def _view(request):
    raise AssertionError("never called")


class _BaseUrlConf:
    urlpatterns = [
        re_path(spa.spa_path_pattern(spa.BASE_NON_SPA_PREFIXES), _view, name="spa")
    ]


class _HubUrlConf:
    urlpatterns = [
        re_path(
            spa.spa_path_pattern(
                (*spa.BASE_NON_SPA_PREFIXES, "ws", "p", "auth/google/callback")
            ),
            _view,
            name="spa",
        )
    ]


def is_spa(path: str, urlconf=_BaseUrlConf) -> bool:
    try:
        return resolve(path, urlconf=urlconf).url_name == "spa"
    except Resolver404:
        return False


class TestSpaPathPattern:
    def test_the_base_prefixes(self):
        assert spa.BASE_NON_SPA_PREFIXES == (
            "api",
            "internal",
            "admin",
            "static",
            "healthz",
            "readyz",
            "csp-report",
        )

    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/demo/items",
            "/demo/items/0192f1e0",
            "/apiary",
            "/administrator",
            "/static-pages/x",
            "/healthzz",
        ],
    )
    def test_spa_paths_get_the_shell(self, path):
        assert is_spa(path)

    @pytest.mark.parametrize(
        "path",
        [
            "/api",
            "/api/",
            "/api/x",
            "/admin/",
            "/admin/login/",
            "/static/a.js",
            "/healthz",
            "/readyz",
            "/csp-report/",
            "/internal/hubs/1/state",
        ],
    )
    def test_django_prefixes_never_get_the_shell(self, path):
        assert not is_spa(path)

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/ws/print", False),
            ("/p/abc", False),
            ("/pos", True),
            ("/auth/google/callback/", False),
            ("/auth/login", True),
        ],
    )
    def test_a_project_adds_its_own_prefixes(self, path, expected):
        assert is_spa(path, urlconf=_HubUrlConf) is expected
