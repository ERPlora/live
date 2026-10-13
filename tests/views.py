"""Views used only by the test suite."""

from django.http import HttpResponse
from django.middleware.csp import get_nonce

from live.spa import render_spa


def csp_probe(request):
    """Answer with the request's CSP nonce, to compare it with the header."""
    return HttpResponse(str(get_nonce(request)))


def spa(request):
    return render_spa(request)


def spa_with_session(request):
    return render_spa(request, extra_json={"session-me": {"user": "ana", "note": "</script><script>alert(1)</script>"}})


def spa_with_config(request):
    return render_spa(request, extra_config={"loginUrl": "https://login.example.com/?hub=a"})


def spa_overriding_config(request):
    return render_spa(request, extra_config={"lang": "xx"})
