"""Expose the loaded setup revision so the wizard can verify a real engine restart."""
from pathlib import Path
import json

# External ComfyUI launchers do not receive the workbench's --extra-model-paths-config.
# Load only our own configuration, without changing a user's extra_model_paths.yaml.
model_config = Path(__file__).with_name('models.json')
if model_config.is_file():
    import folder_paths
    model_root = Path(json.loads(model_config.read_text(encoding='utf-8'))['root'])
    if not model_root.is_absolute():
        raise ValueError('ai-go-play model root must be an absolute path')
    for category in ('diffusion_models', 'text_encoders', 'vae', 'loras',
                     'upscale_models', 'frame_interpolation', 'checkpoints'):
        folder_paths.add_model_folder_path(category, str(model_root / category), is_default=True)

REVISION = Path(__file__).with_name('revision.txt').read_text(encoding='utf-8').strip()


class ManjuSetupRevision:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'revision': ([REVISION],)}}
    RETURN_TYPES = ('STRING',)
    FUNCTION = 'value'
    CATEGORY = 'Manju/安装检查'
    def value(self, revision):
        return (revision,)


NODE_CLASS_MAPPINGS = {'ManjuSetupRevision': ManjuSetupRevision}
