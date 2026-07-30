from rest_framework.renderers import JSONRenderer

from .responses import current_request_id


class ApiJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        renderer_context = renderer_context or {}
        response = renderer_context.get("response")
        request = renderer_context.get("request")

        if response is not None and response.status_code == 204:
            return b""

        is_envelope = (
            isinstance(data, dict)
            and isinstance(data.get("success"), bool)
            and "request_id" in data
        )
        if not is_envelope:
            data = {
                "success": True,
                "data": data,
                "request_id": current_request_id(request),
            }

        return super().render(data, accepted_media_type, renderer_context)
