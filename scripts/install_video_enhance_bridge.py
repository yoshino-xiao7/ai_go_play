"""Copy the bundled Manju video enhancement node to a local ComfyUI."""

import argparse
from pathlib import Path
import shutil


def install(comfy):
    comfy = Path(comfy).resolve()
    if not (comfy / "main.py").is_file() or not (comfy / "folder_paths.py").is_file():
        raise ValueError("Select the ComfyUI directory containing main.py and folder_paths.py.")
    root = Path(__file__).resolve().parents[1]
    source = root / "integrations" / "comfyui_manju_enhance" / "__init__.py"
    target = comfy / "custom_nodes" / "comfyui_manju_enhance" / "__init__.py"
    if not target.resolve().is_relative_to(comfy):
        raise ValueError("The custom node destination leaves the ComfyUI directory.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy", required=True)
    print(install(parser.parse_args().comfy))
