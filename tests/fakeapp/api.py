"""Router of a stand-in app, mounted only by the mount_app_routers test."""

from ninja import Router

router = Router()


@router.get("/fake")
def fake(request):
    return {}
