"""Submit configured shot cards through the same durable generation contract."""
import copy
import math

from .store import DomainError, fingerprint, new_id


def generate_shots(store, generations, production, project_id, payload):
    kinds = payload.get('kinds', ['video', 'audio'])
    selected = payload.get('shot_ids')
    only_missing = payload.get('only_missing', True)
    key = payload.get('request_id') or new_id()
    if not isinstance(key, str) or not 1 <= len(key) <= 120:
        raise DomainError(422, '批次请求编号须为1–120个字符。', 'invalid_request_id')
    if not isinstance(kinds, list) or not kinds or any(k not in ('video', 'audio') for k in kinds) or not isinstance(only_missing, bool):
        raise DomainError(422, '请选择视频或配音，并设置 only_missing 布尔值。', 'invalid_production_batch')
    if selected is not None and (not isinstance(selected, list) or any(not isinstance(s, str) for s in selected)):
        raise DomainError(422, '镜头列表格式无效。', 'invalid_production_batch')
    route = f'production-batch:{project_id}'
    with generations.operation_lock, store.media_lock, store.lock:
        previous = store.request_result(key, route, payload)
        if previous is not None:
            return previous
        document = production.get(project_id)
        expected_revision = payload.get('revision')
        if expected_revision is not None and (isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision != document['revision']):
            raise DomainError(409, '分镜或源卡已更新，请刷新并确认后再生成。', 'revision_conflict', revision=document['revision'])
        shots = document['shots']
        if selected is not None:
            if set(selected) - {s['id'] for s in shots}:
                raise DomainError(422, '所选镜头已不存在，请重新读取分镜。', 'production_shot_missing')
            shots = [s for s in shots if s['id'] in selected]
        result = {'request_id': key, 'jobs': [], 'skipped': [], 'errors': []}
        for shot in shots:
            for kind in dict.fromkeys(kinds):
                note = {'shot_id': shot['id'], 'title': shot['title'], 'kind': kind}
                if only_missing and shot.get(kind + '_version_id'):
                    result['skipped'].append({**note, 'message': '已采用素材，保留当前版本。'})
                    continue
                if kind == 'audio' and not shot.get('dialogue', '').strip():
                    result['skipped'].append({**note, 'message': '此镜头没有台词。'})
                    continue
                canvas = store.canvas(project_id)
                source_id = shot.get(kind + '_node_id')
                source = next((n for n in canvas['nodes'] if n['id'] == source_id), None)
                if not source or source.get('data', {}).get('kind') != kind:
                    result['errors'].append({**note, 'code': 'production_source_missing', 'message': '请先关联已配置的视频或配音创作卡。'})
                    continue
                active = store.conn.execute("SELECT id FROM generation_jobs WHERE project_id=? AND source_node_id=? AND status IN ('pending','submitting','queued','running','collecting','unknown') LIMIT 1", (project_id, source_id)).fetchone()
                if active:
                    result['skipped'].append({**note, 'job_id': active['id'], 'message': '源卡已有未结束任务，未重复提交。'})
                    continue
                draft = copy.deepcopy(source.get('data', {}).get('generation', {}))
                if not draft or draft.get('pending_submission'):
                    result['errors'].append({**note, 'code': 'production_draft_unready', 'message': '源卡尚未配置，或有待核对的提交。'})
                    continue
                request = {k: v for k, v in draft.items() if k in {'video_options','video_mode','duration','audio','speech_options','subject_node_id','workflow_id','prompt','prompt_parts','references','parameters','negative_prompt'}}
                request.update(kind=kind, project_id=project_id, source_node_id=source_id, result_policy='review', request_id='batch:' + fingerprint({'project_id':project_id,'request_id':key,'shot_id':shot['id'],'kind':kind}))
                if kind == 'audio':
                    request['prompt'] = shot['dialogue']
                    request['prompt_parts'] = [{'type': 'text', 'text': shot['dialogue']}]
                else:
                    required = math.ceil(shot['trim_start'] + shot['duration'])
                    if required > 15:
                        result['errors'].append({**note, 'code':'production_generation_too_long', 'message':'当前视频生成最长15秒，请拆分镜头或调整入点与时长。'})
                        continue
                    configured = request.get('duration', 4)
                    if not isinstance(configured, bool) and isinstance(configured, (int, float)) and math.isfinite(configured):
                        request['duration'] = max(configured, required, 4)
                try:
                    job = generations.create(request)
                    draft.update(last_job_id=job['id'])
                    if kind == 'audio':
                        draft.update(prompt=request['prompt'], prompt_parts=request['prompt_parts'])
                    else:
                        draft.update(duration=request.get('duration', 4))
                    source['data']['generation'] = draft
                    canvas['request_id'] = f'batch-card:{job["id"]}'
                    store.save_canvas(project_id, canvas)
                    result['jobs'].append({**note, **job})
                except DomainError as error:
                    result['errors'].append({**note, **error.detail})
        with store.tx():
            store.remember_request(key, route, payload, result)
        return result
