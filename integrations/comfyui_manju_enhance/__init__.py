"""Stream local frame-rate conversion and neural upscaling through ComfyUI."""

from contextlib import contextmanager
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

import folder_paths
import numpy as np
import torch
from torch.nn import functional as F
from comfy import model_management
from comfy.utils import ProgressBar, load_torch_file, tiled_scale


RIFE_WEIGHT = os.path.join('DRBA-RIFE', 'train_log_rife_426_heavy', 'flownet.pkl')
UPSCALE_WEIGHTS = {
    'anime6b': 'RealESRGAN_x4plus_anime_6B.pth',
    'remacri': '4x_foolhardy_Remacri.pth',
}
DEFAULT_METHOD = {'interpolate': 'rife', 'upscale': 'anime6b'}
LOCAL_INPUT = ('-protocol_whitelist', 'file,pipe', '-format_whitelist',
               'matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,avi,mpegts,mpeg,flv,ogg')
CREATE_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: Fraction
    sar: Fraction
    frames: int
    offset: Fraction
    matrix: str
    primaries: str
    transfer: str


def _local_input(name):
    root = Path(folder_paths.get_input_directory()).resolve()
    path = Path(folder_paths.get_annotated_filepath(name)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Video must be a local file in the ComfyUI input directory.')
    return path


def _executables(value):
    # Backend configuration supplies this binary. Never accept shell syntax or a media-tree executable.
    path = Path(value)
    if path.name.lower() not in ('ffmpeg', 'ffmpeg.exe'):
        raise ValueError('Use the configured FFmpeg executable.')
    if not path.is_absolute():
        if path.parent != Path('.'):
            raise ValueError('Use an absolute FFmpeg path or an executable on PATH.')
        path = Path(shutil.which(value) or value)
    path = path.resolve()
    roots = (folder_paths.get_input_directory(), folder_paths.get_output_directory(),
             folder_paths.get_temp_directory())
    if not path.is_file() or any(path.is_relative_to(Path(root).resolve()) for root in roots):
        raise ValueError('The configured local FFmpeg executable is unavailable.')
    probe = path.with_name('ffprobe' + path.suffix)
    if not probe.is_file():
        raise ValueError('The configured FFmpeg needs ffprobe in the same directory.')
    return path, probe


def _fraction(value, default=None):
    try:
        return Fraction(str(value).replace(':', '/'))
    except (ValueError, ZeroDivisionError):
        return default


def _probe(exe, path):
    fields = ('stream=width,height,sample_aspect_ratio,r_frame_rate,avg_frame_rate,time_base,'
              'color_space,color_primaries,color_transfer,field_order'
              ':stream_side_data=rotation:frame=best_effort_timestamp,interlaced_frame:format=start_time')
    cmd = [exe, '-v', 'error', *LOCAL_INPUT, '-select_streams', 'V:0',
           '-show_frames', '-show_streams', '-show_format', '-show_entries', fields,
           '-of', 'json', path]
    proc = subprocess.run(cmd, capture_output=True, creationflags=CREATE_FLAGS)
    if proc.returncode:
        raise ValueError('Cannot read source video: ' + proc.stderr.decode(errors='replace')[-2500:])
    data = json.loads(proc.stdout)
    streams, frames = data.get('streams', []), data.get('frames', [])
    if len(streams) != 1 or not frames:
        raise ValueError('The input needs a readable video stream.')
    stream = streams[0]
    if any(int(item.get('rotation', 0)) % 360 for item in stream.get('side_data_list', [])):
        raise ValueError('Apply the source rotation before enhancing this video.')
    if any(frame.get('interlaced_frame') for frame in frames):
        raise ValueError('Deinterlace the source before enhancing this video.')
    try:
        pts = [int(frame['best_effort_timestamp']) for frame in frames]
    except (KeyError, ValueError) as exc:
        raise ValueError('The input needs usable video frame timestamps.') from exc
    tb = _fraction(stream.get('time_base'))
    if not tb or tb <= 0:
        raise ValueError('The input has an invalid video time base.')
    rates = (_fraction(stream.get(key)) for key in ('r_frame_rate', 'avg_frame_rate'))
    fps = next((rate for rate in rates if rate and rate > 0 and
                all(abs((p - pts[0]) * tb - Fraction(i, rate)) <= tb
                    for i, p in enumerate(pts))), None)
    if fps is None or any(b <= a for a, b in zip(pts, pts[1:])):
        raise ValueError('Enhancement requires a constant-frame-rate source.')
    start = _fraction(data.get('format', {}).get('start_time'), Fraction())
    offset = max(Fraction(), pts[0] * tb - start)
    sar = _fraction(stream.get('sample_aspect_ratio'), Fraction(1))
    sar = sar if sar > 0 else Fraction(1)
    transfer = stream.get('color_transfer')
    if transfer in ('smpte2084', 'arib-std-b67'):
        raise ValueError('HDR enhancement is unavailable. Supply an SDR source.')
    matrix = stream.get('color_space')
    if matrix not in ('bt709', 'bt470bg', 'smpte170m', 'smpte240m', 'fcc', 'bt2020nc'):
        matrix = 'bt709'
    primaries = stream.get('color_primaries')
    if primaries not in ('bt709', 'bt470m', 'bt470bg', 'smpte170m', 'smpte240m', 'film', 'bt2020',
                         'smpte428', 'smpte431', 'smpte432', 'jedec-p22'):
        primaries = 'bt709'
    if transfer not in ('bt709', 'gamma22', 'gamma28', 'smpte170m', 'smpte240m', 'linear',
                        'iec61966-2-1', 'bt2020-10', 'bt2020-12'):
        transfer = 'bt709'
    return VideoInfo(int(stream['width']), int(stream['height']), fps, sar, len(pts),
                     offset, matrix, primaries, transfer)


def _cuts(value, frame_count):
    if not value.strip():
        return set()
    try:
        points = {int(part.strip()) for part in value.split(',')}
    except ValueError as exc:
        raise ValueError('Cuts must be comma-separated source frame numbers.') from exc
    if any(point < 0 or point > frame_count for point in points):
        raise ValueError('A cut is outside the source timeline.')
    return points - {0, frame_count}


def _output(prefix, width, height):
    if not prefix or len(prefix) > 200 or re.search(r'[<>:"|?*\x00-\x1f]', prefix):
        raise ValueError('Use a valid relative output filename prefix.')
    if any(part in ('', '.', '..') for part in prefix.replace('\\', '/').split('/')):
        raise ValueError('Use a valid relative output filename prefix.')
    root = Path(folder_paths.get_output_directory()).resolve()
    if not (root / prefix.replace('\\', '/')).parent.resolve().is_relative_to(root):
        raise ValueError('Output prefix leaves the ComfyUI output directory.')
    folder, name, counter, _, _ = folder_paths.get_save_image_path(prefix, str(root), width, height)
    folder = Path(folder).resolve()
    if not folder.is_relative_to(root):
        raise ValueError('Output prefix leaves the ComfyUI output directory.')
    return root, folder / f'{name}_{counter:05}.mkv'


def _read_frames(pipe, info):
    size = info.height * info.width * 3
    for _ in range(info.frames):
        frame = pipe.read(size)
        if len(frame) != size:
            raise RuntimeError('FFmpeg returned fewer source frames than probed.')
        yield np.frombuffer(frame, np.uint8).reshape(info.height, info.width, 3)
    if pipe.read(1):
        raise RuntimeError('FFmpeg returned more source frames than probed.')


def _tensor(image, device, dtype=torch.float32):
    # Writable storage avoids passing a readonly view over the decoder pipe to Torch.
    return torch.from_numpy(image.copy()).permute(2, 0, 1).unsqueeze(0).to(
        device=device, dtype=dtype).div_(255)


def _image(tensor):
    return tensor.squeeze(0).clamp_(0, 1).mul_(255).round_().to(
        device='cpu', dtype=torch.uint8).permute(1, 2, 0).contiguous().numpy()


class _Rife:
    def __init__(self, device):
        from comfy_extras.nodes_frame_interpolation import FrameInterpolationModelLoader
        path = folder_paths.get_full_path_or_raise('frame_interpolation', RIFE_WEIGHT)
        state = load_torch_file(path, safe_load=True)
        self.device = device
        self.dtype = torch.float16 if model_management.should_use_fp16(device) else torch.float32
        self.model = FrameInterpolationModelLoader._detect_and_load(state).eval().to(
            device=device, dtype=self.dtype)

    def prepare(self, rgb):
        frame = _tensor(rgb, self.device, self.dtype)
        h, w = rgb.shape[:2]
        bottom, right = (-h) % self.model.pad_align, (-w) % self.model.pad_align
        if bottom or right:
            mode = 'reflect' if bottom < h and right < w else 'replicate'
            frame = F.pad(frame, (0, right, 0, bottom), mode=mode)
        return frame, self.model.extract_features(frame)

    def between(self, left, right, fraction, shape):
        frame = self.model(left[0], right[0], float(fraction),
                           cache={'img0': left[1], 'img1': right[1]})
        return _image(frame[:, :, :shape[0], :shape[1]])


def _interpolate(frames, info, rate, cuts, model):
    step = info.fps / rate
    out_index = 0
    left = next(frames)
    prepared_left = None
    for index, right in enumerate(frames, 1):
        prepared_right = None
        hold = model is None or index in cuts or np.array_equal(left, right)
        while out_index * step < index:
            time = out_index * step
            fraction = time - (index - 1)
            if fraction == 0 or hold:
                yield left
            else:
                if prepared_left is None:
                    prepared_left = model.prepare(left)
                if prepared_right is None:
                    prepared_right = model.prepare(right)
                yield model.between(prepared_left, prepared_right, fraction, left.shape)
            out_index += 1
        left, prepared_left = right, prepared_right
    while out_index * step < info.frames:
        yield left
        out_index += 1


def _scale_geometry(info, width, height):
    aspect = Fraction(info.width, info.height) * info.sar
    fit_width = min(Fraction(width), height * aspect)
    fit_height = min(Fraction(height), width / aspect)
    # Neural x4 emits the fitted content. At most two pixels of rounding retain a centered square-pixel canvas.
    pre_width = min(width // 4, max(1, round(fit_width / 4)))
    pre_height = min(height // 4, max(1, round(fit_height / 4)))
    return pre_width, pre_height


class _Anime4x:
    def __init__(self, device, info, width, height, method='anime6b'):
        from spandrel import ModelLoader
        path = folder_paths.get_full_path_or_raise('upscale_models', UPSCALE_WEIGHTS[method])
        model = ModelLoader().load_from_state_dict(load_torch_file(path, safe_load=True))
        if model.scale != 4:
            raise RuntimeError('The selected local upscale model must be 4×.')
        self.device = device
        use_half = (device.type == 'cuda' and model.supports_half
                    and model_management.should_use_fp16(device))
        self.dtype = torch.float16 if use_half else torch.float32
        self.model = model.eval().to(device=device, dtype=self.dtype)
        self.full_frame = use_half
        if use_half:
            self.model.model.to(memory_format=torch.channels_last)
        self.pre_width, self.pre_height = _scale_geometry(info, width, height)
        self.left = (width - self.pre_width * 4) // 2
        self.top = (height - self.pre_height * 4) // 2
        self.shape = (height, width, 3)
        self.tile = 256 if device.type != 'cpu' else 128

    def _forward(self, frame):
        if self.full_frame:
            try:
                return self.model(frame)
            except model_management.OOM_EXCEPTION:
                self.full_frame = False
            model_management.soft_empty_cache()
        while True:
            try:
                return tiled_scale(frame, self.model, tile_x=self.tile, tile_y=self.tile,
                                   overlap=16, upscale_amount=4, output_device='cpu')
            except model_management.OOM_EXCEPTION:
                if self.tile <= 64:
                    raise
                self.tile //= 2
            model_management.soft_empty_cache()

    def __call__(self, rgb):
        frame = _tensor(rgb, self.device)
        if frame.shape[-2:] != (self.pre_height, self.pre_width):
            frame = F.interpolate(frame, size=(self.pre_height, self.pre_width),
                                  mode='bicubic', align_corners=False, antialias=True).clamp_(0, 1)
        if self.dtype == torch.float16:
            frame = frame.to(dtype=self.dtype, memory_format=torch.channels_last)
        enhanced = self._forward(frame)
        rgb = _image(enhanced.float())
        if rgb.shape == self.shape:
            return rgb
        output = np.zeros(self.shape, dtype=np.uint8)
        output[self.top:self.top+rgb.shape[0], self.left:self.left+rgb.shape[1]] = rgb
        return output


def _upscale(frames, model):
    previous = enhanced = None
    for frame in frames:
        if previous is None or not np.array_equal(frame, previous):
            enhanced = model(frame)
        previous = frame
        yield enhanced


@contextmanager
def _pipe(command, logfile, **kwargs):
    with logfile.open('wb') as err:
        process = subprocess.Popen(command, stderr=err, creationflags=CREATE_FLAGS, **kwargs)
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()


def _filter(info, sar):
    matrix = 'bt2020' if info.matrix == 'bt2020nc' else info.matrix
    return (f'scale=out_color_matrix={matrix}:out_range=tv,'
            f'setsar={sar.numerator}/{sar.denominator}:max=10000,format=yuv420p')


def _transcode(exe, source, dest, info, operation, rate, width, height, cuts, model, progress):
    sar = Fraction(1) if operation == 'upscale' else info.sar
    expected = math.ceil(info.frames * rate / info.fps)
    decode_matrix = 'bt2020' if info.matrix == 'bt2020nc' else info.matrix
    decode = [exe, '-hide_banner', '-loglevel', 'error', '-nostdin',
              *LOCAL_INPUT, '-noautorotate', '-i', source, '-map', '0:V:0',
              '-vf', f'scale=in_color_matrix={decode_matrix}:out_range=pc',
              '-fps_mode', 'passthrough', '-threads:v', '1', '-pix_fmt', 'rgb24',
              '-f', 'rawvideo', 'pipe:1']
    encode = [exe, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
              '-itsoffset', f'{float(info.offset):.9f}', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
              '-video_size', f'{width}x{height}', '-framerate', str(rate), '-i', 'pipe:0',
              *LOCAL_INPUT, '-i', source, '-map', '0:v:0', '-map', '1:a?',
              '-vf', _filter(info, sar), '-fps_mode', 'passthrough',
              '-c:v', 'libx264', '-preset', 'fast', '-crf', '15', '-threads:v', '4',
              '-colorspace', info.matrix, '-color_primaries', info.primaries,
              '-color_trc', info.transfer, '-color_range', 'tv', '-c:a', 'copy',
              '-map_metadata', '-1', '-map_chapters', '-1', dest]
    with tempfile.TemporaryDirectory(prefix='manju-enhance-', dir=dest.parent) as temp:
        dlog = Path(temp) / 'decode.log'
        elog = Path(temp) / 'encode.log'
        try:
            with _pipe(decode, dlog, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL) as decoder:
                with _pipe(encode, elog, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL) as encoder:
                    frames = _read_frames(decoder.stdout, info)
                    if operation == 'interpolate':
                        frames = _interpolate(frames, info, rate, cuts, model)
                    else:
                        frames = _upscale(frames, model)
                    count = 0
                    for frame in frames:
                        model_management.throw_exception_if_processing_interrupted()
                        encoder.stdin.write(memoryview(frame))
                        count += 1
                        if progress:
                            progress.update_absolute(count, expected)
                    encoder.stdin.close()
                    if decoder.wait() or encoder.wait() or count != expected:
                        raise RuntimeError(f'Enhancement wrote {count} of {expected} expected video frames.')
        except (RuntimeError, BrokenPipeError) as exc:
            details = '\n'.join(log.read_text(encoding='utf-8', errors='replace')[-2500:]
                                for log in (dlog, elog) if log.is_file()).strip()
            if details:
                raise RuntimeError(f'{exc}\n{details}') from exc
            raise


class ManjuVideoEnhance:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'video': ('STRING', {'default': ''}),
            'operation': (['interpolate', 'upscale'],),
            'fps': ('INT', {'default': 60, 'min': 1, 'max': 120}),
            'width': ('INT', {'default': 3840, 'min': 16, 'max': 7680, 'step': 2}),
            'height': ('INT', {'default': 2160, 'min': 16, 'max': 4320, 'step': 2}),
            'cuts': ('STRING', {'default': ''}),
            'filename_prefix': ('STRING', {'default': 'Manju/enhance'}),
            'ffmpeg': ('STRING', {'default': 'ffmpeg'}),
        }, 'optional': {
            'method': (['auto', 'rife', 'hold', *UPSCALE_WEIGHTS], {'default': 'auto'}),
        }}

    RETURN_TYPES = ()
    FUNCTION = 'enhance'
    OUTPUT_NODE = True
    CATEGORY = 'Manju/视频'

    @torch.inference_mode()
    def enhance(self, video, operation, fps, width, height, cuts, filename_prefix, ffmpeg,
                method='auto'):
        if method == 'auto':
            method = DEFAULT_METHOD.get(operation)
        source = _local_input(video)
        exe, probe = _executables(ffmpeg)
        info = _probe(probe, source)
        points = _cuts(cuts, info.frames)
        if operation == 'interpolate':
            if method not in ('rife', 'hold'):
                raise ValueError('Choose RIFE or original-frame hold for interpolation.')
            width, height = info.width, info.height
            rate = Fraction(fps)
            if not info.fps <= rate <= 120:
                raise ValueError('Target frame rate must be at least the source frame rate and at most 120 fps.')
        elif operation == 'upscale':
            if method not in UPSCALE_WEIGHTS:
                raise ValueError('Choose Anime6B or Remacri for upscaling.')
            if not (16 <= width <= 7680 and 16 <= height <= 4320):
                raise ValueError('Target dimensions are outside the supported range.')
            rate = info.fps
        else:
            raise ValueError('Unknown video enhancement operation.')
        if width % 2 or height % 2:
            raise ValueError('H.264 video enhancement requires even output dimensions.')
        root, destination = _output(filename_prefix, width, height)
        model_management.throw_exception_if_processing_interrupted()
        model = None
        if method != 'hold':
            model_management.unload_all_models()
            model_management.soft_empty_cache()
            device = model_management.get_torch_device()
            model = (_Rife(device) if operation == 'interpolate'
                     else _Anime4x(device, info, width, height, method))
        count = math.ceil(info.frames * rate / info.fps)
        try:
            with tempfile.TemporaryDirectory(prefix='manju-video-', dir=destination.parent) as temp:
                candidate = Path(temp) / 'video.mkv'
                _transcode(exe, source, candidate, info, operation, rate, width, height,
                           points, model, ProgressBar(count))
                if not candidate.is_file() or not candidate.stat().st_size:
                    raise RuntimeError('FFmpeg did not create an enhanced video.')
                candidate.replace(destination)
        finally:
            if model is not None:
                del model
                model_management.soft_empty_cache()
        return {'ui': {'videos': [{
            'filename': destination.name,
            'subfolder': destination.parent.relative_to(root).as_posix() if root != destination.parent else '',
            'type': 'output',
            'format': 'video/x-matroska',
        }]}, 'result': ()}


NODE_CLASS_MAPPINGS = {'ManjuVideoEnhance': ManjuVideoEnhance}
NODE_DISPLAY_NAME_MAPPINGS = {'ManjuVideoEnhance': 'Manju · 本地视频超分和补帧'}
