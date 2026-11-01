"""The single error envelope and the operation error hierarchy."""

import pytest
from django.core.exceptions import ImproperlyConfigured
from live.errors import (
    AppInactive,
    Conflict,
    InvalidPayload,
    LiveMisuse,
    NotFound,
    OperationError,
    PermissionDenied,
    Unauthorized,
)


def test_base_error_defaults_to_400_and_generic_code():
    error = OperationError("Something went wrong.")

    assert error.status == 400
    assert error.code == "error"
    assert error.message == "Something went wrong."
    assert str(error) == "Something went wrong."


def test_reaching_a_client_does_nothing_by_default():
    assert OperationError("Something went wrong.").reached_client() is None


def test_envelope_has_code_and_message_only_when_there_are_no_fields():
    envelope = PermissionDenied("Permission 'demo.manage' is required.").envelope()

    assert envelope == {
        "error": {
            "code": "permission_denied",
            "message": "Permission 'demo.manage' is required.",
        }
    }


def test_invalid_payload_envelope_carries_fields_per_field():
    error = InvalidPayload("Invalid payload.", fields={"name": "Field required"})

    assert error.status == 422
    assert error.envelope() == {
        "error": {
            "code": "invalid_payload",
            "message": "Invalid payload.",
            "fields": {"name": "Field required"},
        }
    }


def test_invalid_payload_without_fields_omits_the_fields_key():
    assert "fields" not in InvalidPayload("Invalid payload.").envelope()["error"]


@pytest.mark.parametrize(
    ("error_class", "status", "code"),
    [
        (Unauthorized, 401, "unauthorized"),
        (PermissionDenied, 403, "permission_denied"),
        (NotFound, 404, "not_found"),
        (AppInactive, 404, "app_inactive"),
        (InvalidPayload, 422, "invalid_payload"),
    ],
)
def test_subclasses_have_their_status_and_code(error_class, status, code):
    error = error_class("message")

    assert isinstance(error, OperationError)
    assert error.status == status
    assert error.code == code
    assert error.envelope()["error"]["code"] == code


def test_conflict_is_409_with_the_domain_code_given_by_the_caller():
    error = Conflict("The item is already done.", code="demo.item_done")

    assert error.status == 409
    assert error.envelope() == {
        "error": {"code": "demo.item_done", "message": "The item is already done."}
    }


def test_conflict_requires_a_domain_code():
    with pytest.raises(TypeError):
        Conflict("The item is already done.")


def test_code_and_status_can_be_overridden_per_instance():
    error = OperationError("Blocked.", code="app_entitlement_blocked", status=402)

    assert error.status == 402
    assert error.code == "app_entitlement_blocked"
    assert OperationError.status == 400
    assert OperationError.code == "error"


def test_an_error_is_final_unless_it_says_when_to_try_again():
    class Busy(OperationError):
        status = 503
        code = "busy"
        retry_after = 1

    assert OperationError("Not found.").retry_after is None
    assert Busy("Busy.").retry_after == 1
    assert OperationError("Busy.", status=503, retry_after=0.5).retry_after == 0.5
    # The envelope says nothing of it: the client hears the status and the code.
    assert Busy("Busy.").envelope() == {"error": {"code": "busy", "message": "Busy."}}


def test_envelope_fields_are_a_copy():
    fields = {"name": "Field required"}
    envelope = InvalidPayload("Invalid payload.", fields=fields).envelope()

    envelope["error"]["fields"]["name"] = "changed"

    assert fields == {"name": "Field required"}


def test_live_misuse_is_a_configuration_error_not_an_operation_error():
    assert issubclass(LiveMisuse, ImproperlyConfigured)
    assert not issubclass(LiveMisuse, OperationError)
