"""Shared API plumbing: error shape (GEN-1), strict timestamps (GEN-7), hidden ids (GEN-18)."""
from rest_framework import exceptions, fields, relations, status
from rest_framework.views import exception_handler as drf_exception_handler


class BusinessError(exceptions.APIException):
    """A business rule refuses the action (GEN-1, GEN-2): 400, or 409 for a race the caller could not see."""

    def __init__(self, code, detail, status_code=status.HTTP_400_BAD_REQUEST):
        super().__init__(detail, code)
        self.status_code = status_code


def exception_handler(exc, context):
    """Rendered bodies: business rule -> {detail, code}; 403 -> {detail, code: "forbidden"} (GEN-1)."""
    response = drf_exception_handler(exc, context)
    if isinstance(exc, BusinessError):
        response.data = {"detail": str(exc.detail), "code": exc.get_codes()}
    elif isinstance(exc, exceptions.PermissionDenied):
        response.data = {"detail": str(exc.detail), "code": "forbidden"}
    return response


def make_timestamps_strict():
    """GEN-7: a timestamp without an offset is a 400.

    Patches DRF's DateTimeField itself (called once from AccountsConfig.ready), so every
    ModelSerializer and plain serializer gets it with nothing to remember or import.
    """
    original = fields.DateTimeField.to_internal_value

    def to_internal_value(self, value):
        if isinstance(value, str):
            try:
                parsed = fields.parse_datetime(value)
            except ValueError:
                parsed = None  # malformed: the original raises the normal "wrong format" error
            if parsed is not None and parsed.utcoffset() is None:
                self.fail("invalid", format="an ISO 8601 timestamp with an offset, e.g. 2027-01-11T14:00:00Z")
        return original(self, value)

    fields.DateTimeField.to_internal_value = to_internal_value


class VisibleRelatedField(relations.PrimaryKeyRelatedField):
    """Id of an object the caller may see: pass a queryset already scoped to them.

    An id outside it answers like a missing one, "Not found." (GEN-18).
    """

    default_error_messages = {"does_not_exist": "Not found."}
