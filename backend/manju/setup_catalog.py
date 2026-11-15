"""Published model inventory and public Quark listing. Never reads browser credentials."""
from __future__ import annotations

import json
from pathlib import Path
import httpx

PROJECT = Path(__file__).resolve().parents[2]
PACK_NAMES = {
    '01-qwen-image': ('Qwen Image', '文生图 · 参考图 · 图片编辑'),
    '02-h3-image': ('H3 图像', '图像创作与提示词增强'),
    '03-h3-video': ('H3 视频', '标准视频与音色设计'),
    '04-h3-turbo': ('H3 Turbo', '8 步视频生成'),
    '05-indextts': ('IndexTTS 配音', '参考声音生成对白'),
    '06-indextts-emotion': ('文本情绪', '用文字引导语气'),
    '07-latentsync': ('LatentSync 口型', '视频与对白同步'),
    '08-video-enhance': ('视频后期', '插帧与超分辨率'),
}


def catalog(project=PROJECT):
    data = json.loads((project / 'release/models.json').read_text(encoding='utf-8'))
    hashes = dict(line.split('  ', 1)[::-1] for line in (project / 'release/model-checksums.sha256').read_text().splitlines() if line.strip())
    for item in data['files']:
        item['sha256'] = hashes[item['path']]
        # Shared weights are stored once, in the first owning pack in the share.
        item['download_path'] = item['packs'][0] + '/models/' + item['path']
    for pack in data['packs']:
        name, description = PACK_NAMES.get(pack['id'], (pack['name'], ''))
        files = [f for f in data['files'] if pack['id'] in f['packs']]
        pack.update(name=name, description=description, bytes=sum(f['size'] for f in files), count=len(files))
    sources = json.loads((project / 'release/setup-sources.json').read_text(encoding='utf-8'))
    data['share'] = sources['models_share']
    data['mirrors'] = sources.get('models_mirrors', [])
    data['total_bytes'] = sum(f['size'] for f in data['files'])
    return data


def share_inventory(share, *, transport=None, check_cancelled=lambda: None):
    """Bounded, paginated public share scan; no account token is needed for listings."""
    base = 'https://drive-pc.quark.cn/1/clouddrive/share/sharepage/'
    with httpx.Client(timeout=15, transport=transport, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://pan.quark.cn/'}) as client:
        response = client.post(base + 'token', params={'pr': 'ucpro', 'fr': 'pc'}, json={'pwd_id': share['id'], 'passcode': share['passcode']})
        response.raise_for_status()
        token = response.json()
        if token.get('code') != 0 or not token.get('data', {}).get('stoken'):
            raise ValueError(token.get('message') or '分享无法读取，请检查链接和提取码。')
        pending, files, visited = [('0', '')], [], set()
        while pending:
            fid, prefix = pending.pop(0)
            if fid in visited:
                continue
            visited.add(fid)
            if len(visited) > 200:
                raise ValueError('分享目录超出扫描范围。')
            for page in range(1, 21):
                check_cancelled()
                response = client.get(base + 'detail', params={'pr': 'ucpro', 'fr': 'pc', 'pwd_id': share['id'], 'stoken': token['data']['stoken'], 'pdir_fid': fid, '_page': page, '_size': 100})
                response.raise_for_status()
                result = response.json()
                if result.get('code') != 0:
                    raise ValueError(result.get('message') or '读取分享目录失败。')
                rows = result.get('data', {}).get('list', [])
                for item in rows:
                    name = item['file_name']
                    if name in ('.', '..') or '/' in name or '\\' in name:
                        raise ValueError('分享目录包含无效文件名。')
                    path = f'{prefix}/{name}'.lstrip('/')
                    if item.get('dir'):
                        pending.append((item['fid'], path))
                    else:
                        files.append({'path': path, 'size': item.get('size', 0)})
                if len(rows) < 100:
                    break
            else:
                raise ValueError('分享文件超出扫描范围。')
    return files


def match_share(files, inventory):
    remote = {f['path'].split('/models/', 1)[1]: f for f in inventory if '/models/' in f['path']}
    return [{'path': f['path'], 'status': 'listed' if remote.get(f['path'], {}).get('size') == f['size'] else 'missing_or_changed',
             'remote_path': remote.get(f['path'], {}).get('path')} for f in files]
