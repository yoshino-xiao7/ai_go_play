import pytest

from manju.generation import GenerationService
from manju.store import DomainError


@pytest.mark.parametrize(("profile", "default", "alternate"), [
    ("builtin-video-interpolate-local", "rife", "hold"),
    ("builtin-video-upscale-local", "anime6b", "remacri"),
])
def test_video_enhancement_mode_is_backward_compatible_and_operation_specific(profile, default, alternate):
    request = {"kind": "video", "workflow_id": profile, "project_id": "project", "prompt": "",
               "references": [{"version_id": "input", "media_type": "video"}]}
    normalize = GenerationService._validate_request
    assert normalize(request)["enhance_options"]["method"] == default
    assert normalize({**request, "enhance_options": {"method": alternate}})["enhance_options"]["method"] == alternate
    unsupported = "remacri" if default == "rife" else "hold"
    with pytest.raises(DomainError) as error:
        normalize({**request, "enhance_options": {"method": unsupported}})
    assert error.value.detail["code"] == "video_enhance_method"
