"""URLconf for the test suite; tests add their own routes when they need them."""

from django.urls import path

from live.csp import csp_report
from tests import views

urlpatterns = [
    path("csp-report/", csp_report),
    path("csp-probe/", views.csp_probe),
    path("spa/", views.spa),
    path("spa/session/", views.spa_with_session),
    path("spa/config/", views.spa_with_config),
    path("spa/config-clash/", views.spa_overriding_config),
]

# --- Live stream (P5: live.live_view) ------------------------------------------------------------
from live.live_view import live_stream  # noqa: E402

urlpatterns += [path("api/live", live_stream)]
# --- end P5 --------------------------------------------------------------------------------------
