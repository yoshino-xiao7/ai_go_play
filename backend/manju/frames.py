"""Flatten image/text placements within a canvas frame into a library PNG."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .media import probe_media
from .store import DomainError, fingerprint, new_id


def render_frame(store, project_id, frame_id, payload):
    key = payload.get('request_id') or new_id()
    if not isinstance(key, str) or not 1 <= len(key) <= 200:
        raise DomainError(422, '请求编号无效。', 'invalid_request_id')
    scale = payload.get('scale', 1)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or not .25 <= scale <= 4:
        raise DomainError(422, '合成缩放须为0.25–4。', 'invalid_frame_scale')
    route = f'frame-render:{project_id}:{frame_id}'
    token = fingerprint({'project_id':project_id,'frame_id':frame_id,'request_id':key})
    node_id = f'frame-result-{token[:24]}'
    request_hash = fingerprint(payload)
    with store.media_lock, store.lock:
        old = store.request_result(key, route, payload)
        if old is not None:
            return old
        canvas = store.canvas(project_id)
        recovered = next((node for node in canvas['nodes'] if node['id'] == node_id), None)
        if recovered:
            metadata = recovered.get('data', {}).get('composite', {})
            if metadata.get('request_hash') != request_hash or metadata.get('frame_id') != frame_id:
                raise DomainError(409, '相同请求编号已用于其他画框合成内容。', 'idempotency_conflict')
            version_id = recovered['data']['asset_version_id']
            result = {'asset_id':store.version(version_id)['asset_id'],'version_id':version_id,'node_id':node_id}
            with store.tx():
                store.remember_request(key, route, payload, result)
            return result
        if payload.get('revision', canvas['revision']) != canvas['revision']:
            raise DomainError(409, '画布已更新，请保存并重新合成。', 'revision_conflict')
        nodes = {n['id']: n for n in canvas['nodes']}
        frame = nodes.get(frame_id)
        if not frame or frame.get('type') != 'frame':
            raise DomainError(422, '请选择画幅框。', 'frame_missing')

        def position(node):
            x, y = node['position']['x'], node['position']['y']
            parent = node.get('parentId')
            while parent:
                item = nodes[parent]
                x += item['position']['x']; y += item['position']['y']
                parent = item.get('parentId')
            return x, y

        def size(node):
            style = node.get('style', {})
            return float(style.get('width', node.get('width', 264))), float(style.get('height', node.get('height', 214)))

        fx, fy = position(frame); fw, fh = size(frame)
        width, height = round(fw * scale), round(fh * scale)
        if min(width, height) < 16 or max(width, height) > 8192 or width * height > 32_000_000:
            raise DomainError(422, '画框输出须为16–8192像素，面积不超过3200万像素。', 'frame_dimensions')
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        inputs = []
        for node in sorted(canvas['nodes'], key=lambda n: n.get('zIndex', 0)):
            if node['id'] == frame_id or node.get('type') in ('frame', 'group') or node.get('hidden'):
                continue
            x, y = position(node); w, h = size(node)
            if x + w <= fx or y + h <= fy or x >= fx + fw or y >= fy + fh:
                continue
            data = node.get('data', {})
            version_id = data.get('asset_version_id')
            if node.get('type') == 'text':
                layer = Image.new('RGBA', (max(1, round(w*scale)), max(1, round(h*scale))), (0,0,0,0))
                fontpath = next((p for p in [Path('C:/Windows/Fonts/msyh.ttc'),Path('C:/Windows/Fonts/simhei.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')] if p.exists()), None)
                font = ImageFont.truetype(str(fontpath), max(10, round(22*scale))) if fontpath else ImageFont.load_default()
                draw = ImageDraw.Draw(layer)
                lines = []
                for raw in str(data.get('text', '')).splitlines():
                    line = ''
                    for char in raw:
                        if line and draw.textlength(line+char,font=font) > layer.width-12*scale:
                            lines.append(line); line = ''
                        line += char
                    lines.append(line)
                draw.multiline_text((6*scale,6*scale), '\n'.join(lines), fill=data.get('text_color','#ffffff'), font=font, spacing=6*scale)
            elif version_id:
                version = store.version(version_id)
                if not version['mime'].startswith('image/'):
                    raise DomainError(422, '画框合成仅支持图片和文字，请将视频/音频移出此画框。', 'frame_media_type')
                if version.get('missing') or not Path(version['path']).is_file():
                    raise DomainError(422, '画框引用的图片原件缺失。', 'frame_media_missing')
                with Image.open(version['path']) as original:
                    original = ImageOps.exif_transpose(original).convert('RGBA')
                    target_size = (max(1,round(w*scale)), max(1,round(h*scale)))
                    fitted = ImageOps.contain(original, target_size, Image.Resampling.LANCZOS)
                    layer = Image.new('RGBA', target_size, (0,0,0,0))
                    layer.alpha_composite(fitted, ((target_size[0]-fitted.width)//2,(target_size[1]-fitted.height)//2))
                inputs.append(version_id)
            else:
                continue
            opacity = data.get('opacity', 1)
            if isinstance(opacity, bool) or not isinstance(opacity, (int,float)) or not math.isfinite(opacity) or not 0 <= opacity <= 1:
                raise DomainError(422, '图层不透明度须为0–1。', 'frame_opacity')
            if opacity < 1:
                layer.putalpha(layer.getchannel('A').point(lambda a: round(a*opacity)))
            image.alpha_composite(layer, (round((x-fx)*scale), round((y-fy)*scale)))
        if not image.getbbox():
            raise DomainError(422, '画框内没有可合成的图片或文字。', 'frame_empty')
        name = store.validate_name(payload.get('name') or (frame.get('data',{}).get('title') or '画框合成'))
        if not name.lower().endswith('.png'):
            name += '.png'
        temp = store.root / 'temp' / f'frame-{new_id()}.png'
        try:
            image.save(temp)
            digest = hashlib.sha256(temp.read_bytes()).hexdigest()
            asset = store.ingest(temp, name, probe_media(temp, name), digest, project_id=project_id, request_id='frame-asset:'+token, source='composite')
            version_id = asset['imported_version_id']
            canvas['nodes'].append({'id':node_id,'type':'media','position':{'x':fx+fw+80,'y':fy},'style':{'width':264,'height':214},'data':{'kind':'image','title':name,'asset_version_id':version_id,'composite':{'frame_id':frame_id,'input_versions':inputs,'request_hash':request_hash}}})
            canvas['request_id'] = 'frame-canvas:'+token
            store.save_canvas(project_id, canvas)
            result = {'asset_id':asset['id'],'version_id':version_id,'node_id':node_id}
            with store.tx():
                store.remember_request(key, route, payload, result)
            return result
        finally:
            temp.unlink(missing_ok=True)
