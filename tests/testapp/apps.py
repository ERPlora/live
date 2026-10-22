"""Minimal app used only by the test suite: a module (``kind = "app"``) with its metadata.

It declares one step, one panel and one counter of the Home so that the ``live`` checks run over real
declarations (its query ``testapp.thing.list``, its permission, its event).
"""

from live.meta import BellCounter, Category, LiveAppConfig, Nav, SetupCheck, SetupStep, Widget


class TestAppConfig(LiveAppConfig):
    name = "tests.testapp"
    label = "testapp"
    kind = "app"
    icon = "ion:cube-outline"
    category = Category.ORGANIZATION
    summary = "Things to test the live package with."
    description = "A module of the test suite: its models, operations and live queries."
    verticals = ["restaurant"]
    navigation = [Nav(id="testapp", label="Things", icon="ion:cube-outline", path="/testapp")]
    permissions = ["testapp.view", "testapp.manage"]
    role_permissions = {"admin": ["testapp.*"]}
    setup = [
        SetupStep(
            key="things",
            operation="testapp.thing.list",
            configured_when=[SetupCheck(field="name", truthy=True)],
            title="Add your first thing",
            route="/testapp",
            permission="testapp.manage",
            refresh_on=["testapp.thing.created"],
        )
    ]
    widgets = [
        Widget(
            key="things",
            title="Things",
            kind="bar-list",
            operation="testapp.thing.list",
            map={"label": "name"},
            permission="testapp.view",
            refresh_on=["testapp.thing.created"],
        )
    ]
    bell = [
        BellCounter(
            key="things",
            operation="testapp.thing.list",
            route="/testapp",
            label="Things",
            permission="testapp.view",
            refresh_on=["testapp.thing.created"],
        )
    ]
