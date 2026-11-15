"""Run inside an isolated inference environment, without loading GPU model weights."""
import json
from pathlib import Path
import sys
import types


def main():
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    sys.path.insert(0, config["repo"])
    import numpy as np
    import torch
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Inference requires Python 3.11")
    if np.__version__ != '1.26.4' or torch.__version__ != '2.8.0+cu128':
        raise RuntimeError('Runtime dependencies changed; rerun the pinned installer.')
    allowed = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), Path(config['repo']).resolve()]
    external = [entry for entry in sys.path if entry and not any(Path(entry).resolve().is_relative_to(base) for base in allowed)]
    if external:
        raise RuntimeError('Runtime imports from another environment: ' + repr(external))
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable. Check the NVIDIA driver and the CUDA PyTorch installation.")
    # Detect unsupported GPU architectures before reporting installation success.
    x = torch.ones((16, 16), device="cuda", dtype=torch.float16)
    assert float((x @ x)[0, 0]) == 16
    torch.cuda.synchronize()
    if config["kind"] == "speech":
        from indextts.infer_v2_5 import IndexTTS2
        from indextts.utils.front import TextNormalizer
        from indextts.utils.ja_g2p import JapaneseG2PProcessor
        normalizer = TextNormalizer()
        normalizer.load()
        JapaneseG2PProcessor()
        import soundfile
        if config.get("emotion"):
            from transformers import AutoTokenizer
            AutoTokenizer.from_pretrained(str(Path(config["model_dir"]) / "qwen0.6bemo4-merge"), local_files_only=True)
    else:
        import cv2
        # The worker replaces InsightFace with YuNet before importing the pipeline.
        detector = types.ModuleType("latentsync.utils.face_detector")
        detector.FaceDetector = object
        sys.modules[detector.__name__] = detector
        from latentsync.pipelines.lipsync_pipeline import LipsyncPipeline
        from latentsync.whisper.whisper.tokenizer import get_tokenizer
        get_tokenizer(multilingual=True)
        model = cv2.FaceDetectorYN.create(config["face_detector"], "", (320, 320))
        model.detect(np.zeros((320, 320, 3), dtype=np.uint8))
    result = {"kind": config["kind"], "python": sys.version.split()[0], "torch": torch.__version__,
              "numpy": np.__version__, "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(),
              "bf16": torch.cuda.is_bf16_supported(), "gpu_total_bytes": torch.cuda.get_device_properties(0).total_memory,
              "isolated_sys_path": sys.path}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
