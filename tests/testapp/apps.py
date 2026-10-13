"""Minimal app used only by the test suite: a module (``kind = "app"``) with its metadata."""

from live.meta import Category, LiveAppConfig, Nav


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
