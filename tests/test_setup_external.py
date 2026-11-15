"""A pre-existing ComfyUI launcher must load models selected in the wizard."""
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

from manju.setup_catalog import catalog
from manju.setup_install import install_setup_revision


def test_external_launcher_loads_selected_models_without_extra_command_line(tmp_path, monkeypatch):
    project = Path(__file__).resolve().parents[1]
    comfy = tmp_path / 'existing-comfy'
    comfy.mkdir()
    original = comfy / 'extra_model_paths.yaml'
    original.write_text('personal: unchanged\n')
    model_root = tmp_path / '自选模型'
    paths = {}
    def add(category, path, is_default=False):
        assert is_default is True
        paths[category] = path
    monkeypatch.setitem(sys.modules, 'folder_paths', SimpleNamespace(add_model_folder_path=add))
    installation = {'comfy_path': str(comfy)}
    install_setup_revision(project, installation, 'first', models_root=model_root)
    node = comfy / 'custom_nodes/comfyui_manju_setup/__init__.py'
    loaded = runpy.run_path(str(node))
    assert paths['vae'] == str(model_root / 'vae')
    assert paths['diffusion_models'] == str(model_root / 'diffusion_models')
    assert len(paths) == 7
    install_setup_revision(project, installation, 'second', models_root=tmp_path / 'another')
    # Running engine keeps its loaded revision until an actual import/restart.
    assert loaded['ManjuSetupRevision'].INPUT_TYPES()['required']['revision'] == (['first'],)
    restarted = runpy.run_path(str(node))
    assert restarted['ManjuSetupRevision'].INPUT_TYPES()['required']['revision'] == (['second'],)
    assert paths['vae'] == str(tmp_path / 'another/vae')
    assert original.read_text() == 'personal: unchanged\n'


def test_shared_model_download_location_points_to_owning_pack():
    shared = next(f for f in catalog()['files'] if '03-h3-video' in f['packs'] and '02-h3-image' in f['packs'])
    assert shared['download_path'] == '02-h3-image/models/' + shared['path']
