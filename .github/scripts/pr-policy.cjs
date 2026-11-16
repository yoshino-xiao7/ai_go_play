// Trusted metadata only. Never check out, import, or execute pull-request code.
const fs = require('node:fs');
const config = require('../governance.json');
const VERSION = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;

function route(pr, policy = config) {
  if (pr.base.repo.full_name !== policy.repository) return { ok: false, reason: '仓库不匹配。' };
  if (pr.base.ref === policy.integration_branch) {
    if (pr.head.repo?.full_name === policy.repository) {
      return pr.head.ref === policy.development_branch && pr.user.login === policy.owner
        ? { ok: true, release: false }
        : { ok: false, reason: '上游开发 PR 须由仓库所有者从 dev 提交到 integration。社区请从自己的 fork 提交到 integration。' };
    }
    return pr.head.repo?.full_name
      ? { ok: true, release: false }
      : { ok: false, reason: '无法确认 PR 的来源仓库，请从有效的 fork 重新提交到 integration。' };
  }
  if (pr.base.ref === policy.release_branch && pr.head.ref === policy.integration_branch &&
      pr.head.repo?.full_name === policy.repository && pr.user.login === policy.owner) {
    const version = /^Release-Version:\s*(\S+)\s*$/m.exec(pr.body || '')?.[1];
    return VERSION.test(version || '') ? { ok: true, release: true, version }
      : { ok: false, fixable: true, reason: '发布 PR 须由仓库所有者填写 Release-Version: X.Y.Z；版本号由合并者确认。' };
  }
  return { ok: false, reason: 'integration 是唯一集成入口。开发与社区 PR 请以 integration 为目标；main 仅接受仓库所有者发起的本仓库 integration → main 发布 PR，dev 不接收 PR。请按 CONTRIBUTING.md 修改目标分支后重新打开，或重新提交 PR。' };
}

function reviewed(pr, comments, reviews, decision, policy = config) {
  const sha = pr.head.sha;
  const decisions = reviews.filter(r => r.user?.login === policy.owner && r.commit_id === sha &&
    ['APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'].includes(r.state))
    .map(r => ({ time: r.submitted_at || '', ok: r.state === 'APPROVED' }));
  const approve = decision.release ? `/release-confirm ${decision.version} ${sha}` : `/reviewed ${sha}`;
  for (const c of comments.filter(c => c.user?.login === policy.owner)) {
    if ((c.body || '').trim() === approve || (c.body || '').trim() === `/reject ${sha}`) {
      decisions.push({ time: c.updated_at || c.created_at, ok: c.body.trim() === approve, explicit: true });
    }
  }
  decisions.sort((a, b) => a.time.localeCompare(b.time));
  const latest = decisions.at(-1);
  // Release approval must confirm the exact version and current integration SHA.
  return !!latest?.ok && latest.explicit === true;
}

async function run() {
  const event = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'));
  const number = event.pull_request?.number || (event.issue?.pull_request && event.issue.number);
  if (!number || process.env.GITHUB_REPOSITORY !== config.repository) return;
  const api = async (method, path, body) => {
    const response = await fetch(`https://api.github.com/repos/${config.repository}${path}`, {
      method, headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`GitHub ${method} ${path.split('?')[0]}: HTTP ${response.status}`);
    return response.status === 204 ? null : response.json();
  };
  const all = async path => {
    const result = [];
    for (let page = 1; ; page++) {
      const rows = await api('GET', `${path}?per_page=100&page=${page}`);
      result.push(...rows);
      if (rows.length < 100) return result;
    }
  };
  const pr = await api('GET', `/pulls/${number}`);
  if (pr.state !== 'open') return;
  const decision = route(pr);
  const [comments, reviews] = await Promise.all([all(`/issues/${number}/comments`), all(`/pulls/${number}/reviews`)]);
  const publishCheck = async (name, ok, summary) => {
    await api('POST', '/check-runs', { name, head_sha: pr.head.sha, status: 'completed', conclusion: ok ? 'success' : 'failure',
      external_id: `pr-${number}/${name}`, output: { title: ok ? '符合仓库流程' : '需要按贡献规范处理', summary } });
  };
  // Re-fetch before writing: do not approve an outdated PR head after a push.
  const fresh = await api('GET', `/pulls/${number}`);
  if (fresh.head.sha !== pr.head.sha || fresh.base.ref !== pr.base.ref || fresh.body !== pr.body || fresh.state !== 'open') return;
  await publishCheck(`policy/${pr.base.ref}/route`, decision.ok, decision.ok ? '目标分支和来源符合开发流程。' : decision.reason);
  const approved = decision.ok && reviewed(pr, comments, reviews, decision);
  await publishCheck(`policy/${pr.base.ref}/review`, approved, approved ? '仓库所有者已确认当前提交。' :
    decision.release ? `等待 @${config.owner} 评论：\n\n\`/release-confirm ${decision.version} ${pr.head.sha}\`` :
      `等待 @${config.owner} 审核当前提交后评论：\n\n\`/reviewed ${pr.head.sha}\`\n\n新增提交后必须重新确认；自审只允许仓库所有者本人记录。`);
  if (!decision.ok) {
    const marker = '<!-- ai-go-play:branch-policy -->';
    if (!comments.some(c => c.user?.type === 'Bot' && c.body?.includes(marker) && c.body.includes(decision.reason))) {
      await api('POST', `/issues/${number}/comments`, { body: `${marker}\n${decision.reason}\n\n规范：https://github.com/${config.repository}/blob/main/CONTRIBUTING.md` });
    }
    if (!decision.fixable) await api('PATCH', `/pulls/${number}`, { state: 'closed' });
  }
}

module.exports = { route, reviewed, run };
if (require.main === module) run().catch(e => { console.error(e.message); process.exitCode = 1; });
