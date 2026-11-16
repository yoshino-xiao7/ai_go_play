const test = require('node:test');
const assert = require('node:assert/strict');
const { route, reviewed } = require('../.github/scripts/pr-policy.cjs');
const repo = 'yoshino-xiao7/ai_go_play', owner = 'yoshino-xiao7', sha = 'a'.repeat(40);
const pr = (base = 'integration', head = 'dev', headRepo = repo, user = owner) => ({base:{ref:base,repo:{full_name:repo}},head:{ref:head,sha,repo:{full_name:headRepo}},user:{login:user},body:'Release-Version: 0.2.0'});
const comment = (body, user = owner, time = '2026-11-14T02:00:00Z') => ({body,user:{login:user},created_at:time,updated_at:time});
test('dev and fork contributions use integration', () => {
  assert.equal(route(pr()).ok,true);
  assert.equal(route(pr('integration','feat/a','contributor/fork','contributor')).ok,true);
});
test('same-repository integration PRs must come from the owner’s dev', () => {
  for (const p of [pr('integration','main'),pr('integration','feat/a'),pr('integration','dev',repo,'contributor')]) {
    assert.equal(route(p).ok,false);
  }
  const missing = pr('integration','dev'); missing.head.repo = null;
  assert.equal(route(missing).ok,false);
});
test('direct main/dev PRs are rejected including fork branches named integration', () => {
  for (const p of [pr('main','dev'),pr('main','feat/a'),pr('main','integration','other/fork'),pr('dev','feat/a'),pr('main','integration',repo,'contributor')]) assert.equal(route(p).ok,false);
});
test('owner release PR requires explicit semantic version', () => {
  const p=pr('main','integration');assert.equal(route(p).version,'0.2.0');
  p.body='Release-Version: latest';assert.equal(route(p).ok,false);
});
test('only exact owner approval of current head is accepted', () => {
  const p=pr(),d=route(p);
  assert.equal(reviewed(p,[comment(`/reviewed ${sha}`)],[],d),true);
  assert.equal(reviewed(p,[comment(`/reviewed ${sha}`,'other')],[],d),false);
  assert.equal(reviewed(p,[comment('/reviewed '+'b'.repeat(40))],[],d),false);
});
test('release approval binds both version and SHA', () => {
  const p=pr('main','integration'),d=route(p);
  assert.equal(reviewed(p,[comment(`/reviewed ${sha}`)],[],d),false);
  assert.equal(reviewed(p,[comment(`/release-confirm 0.3.0 ${sha}`)],[],d),false);
  assert.equal(reviewed(p,[comment(`/release-confirm 0.2.0 ${sha}`)],[],d),true);
});
test('later rejection invalidates approval', () => {
  const p=pr(),d=route(p);
  const comments=[comment(`/reviewed ${sha}`),comment(`/reject ${sha}`,owner,'2026-11-14T03:00:00Z')];
  assert.equal(reviewed(p,comments,[],d),false);
});
test('native approval alone cannot bypass explicit final confirmation', () => {
  const p=pr();
  assert.equal(reviewed(p,[],[{user:{login:owner},commit_id:sha,state:'APPROVED',submitted_at:'2026-11-14T03:00:00Z'}],route(p)),false);
});

async function exercisePolicy(t, initial, { comments = [], fresh = initial } = {}) {
  const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-go-play-policy-'));
  const event = path.join(directory, 'event.json');
  fs.writeFileSync(event, JSON.stringify({ issue: { number: 12, pull_request: {} } }));
  const originalFetch = global.fetch;
  const originalEnv = { GITHUB_EVENT_PATH: process.env.GITHUB_EVENT_PATH, GITHUB_REPOSITORY: process.env.GITHUB_REPOSITORY };
  t.after(() => {
    global.fetch = originalFetch;
    for (const [key, value] of Object.entries(originalEnv)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    fs.rmSync(directory, { recursive: true, force: true });
  });
  process.env.GITHUB_EVENT_PATH = event;
  process.env.GITHUB_REPOSITORY = repo;
  const writes = [];
  let reads = 0;
  global.fetch = async (url, options) => {
    const suffix = new URL(url).pathname.replace(`/repos/${repo}`, '');
    let response;
    if (options.method !== 'GET') {
      writes.push({ method: options.method, suffix, body: JSON.parse(options.body) });
      response = {};
    } else if (suffix === '/pulls/12') response = { ...(reads++ ? fresh : initial), state: 'open' };
    else if (suffix === '/issues/12/comments') response = comments;
    else if (suffix === '/pulls/12/reviews') response = [];
    else throw new Error(`Unexpected API request: ${suffix}`);
    return { ok: true, status: 200, json: async () => response };
  };
  await require('../.github/scripts/pr-policy.cjs').run();
  return writes;
}

test('wrong-target PR is explained and closed through the API', async t => {
  const writes = await exercisePolicy(t, pr('main', 'dev'));
  assert.ok(writes.some(w => w.suffix === '/issues/12/comments' && w.body.body.includes('integration 是唯一集成入口')));
  assert.ok(writes.some(w => w.method === 'PATCH' && w.body.state === 'closed'));
  assert.equal(writes.find(w => w.body.name === 'policy/main/route').body.conclusion, 'failure');
});

test('valid release source without version fails but remains open', async t => {
  const p = pr('main', 'integration'); p.body = '';
  const writes = await exercisePolicy(t, p);
  assert.ok(writes.some(w => w.body.name === 'policy/main/route' && w.body.conclusion === 'failure'));
  assert.ok(!writes.some(w => w.body.state === 'closed'));
});

test('current owner confirmation produces target-specific successful checks', async t => {
  const writes = await exercisePolicy(t, pr(), { comments: [comment(`/reviewed ${sha}`)] });
  assert.deepEqual(writes.map(w => [w.body.name, w.body.conclusion]), [
    ['policy/integration/route', 'success'], ['policy/integration/review', 'success'],
  ]);
});

test('a head change while fetching reviews never approves the new head', async t => {
  const initial = pr(), fresh = pr(); fresh.head.sha = 'b'.repeat(40);
  const writes = await exercisePolicy(t, initial, { fresh, comments: [comment(`/reviewed ${sha}`)] });
  assert.deepEqual(writes, []);
});

test('replayed wrong-target events do not duplicate explanatory comments', async t => {
  const p = pr('main', 'dev');
  const writes = await exercisePolicy(t, p, { comments: [{ user: { type: 'Bot' }, body: `<!-- ai-go-play:branch-policy -->\n${route(p).reason}` }] });
  assert.ok(!writes.some(w => w.suffix === '/issues/12/comments'));
  assert.ok(writes.some(w => w.body.state === 'closed'));
});

test('release requires the owner, main, exact version, PR and explicit confirmation', () => {
  const { assertReleaseInputs } = require('../.github/scripts/release.cjs');
  const env = { GITHUB_REPOSITORY: repo, GITHUB_REF: 'refs/heads/main', GITHUB_ACTOR: owner, GITHUB_SHA: sha,
    RELEASE_VERSION: '1.2.3', RELEASE_PR: '12', RELEASE_CONFIRM: 'true' };
  assert.doesNotThrow(() => assertReleaseInputs(env));
  for (const change of [{GITHUB_REPOSITORY:'other/fork'}, {GITHUB_REF:'refs/heads/dev'}, {GITHUB_ACTOR:'other'},
    {RELEASE_VERSION:'latest'}, {RELEASE_VERSION:'1.2.3-beta'}, {RELEASE_PR:'0'}, {RELEASE_CONFIRM:'false'}, {GITHUB_SHA:''}]) {
    assert.throws(() => assertReleaseInputs({...env,...change}));
  }
});

test('release verifies actual archive bytes and checksum file before any upload', t => {
  const { readArtifacts } = require('../.github/scripts/release.cjs');
  const fs = require('node:fs'), path = require('node:path'), os = require('node:os'), crypto = require('node:crypto');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-go-play-release-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const archive = Buffer.from('fixture archive bytes');
  const asset = 'ai-go-play-v1.2.3.zip';
  const digest = crypto.createHash('sha256').update(archive).digest('hex');
  fs.writeFileSync(path.join(directory, asset), archive);
  fs.writeFileSync(path.join(directory, 'SHA256SUMS'), `${digest}  ${asset}\n`);
  fs.writeFileSync(path.join(directory, 'release-manifest.json'), JSON.stringify({version:'1.2.3',commit:sha,asset,size:archive.length,sha256:digest,model_weights_included:false}));
  assert.equal(readArtifacts(directory, '1.2.3', sha).length, 3);
  assert.throws(() => readArtifacts(directory, '1.2.4', sha), /manifest/);
  assert.throws(() => readArtifacts(directory, '1.2.3', 'b'.repeat(40)), /manifest/);
  fs.writeFileSync(path.join(directory, asset), 'changed after build');
  assert.throws(() => readArtifacts(directory, '1.2.3', sha), /SHA-256/);
  fs.writeFileSync(path.join(directory, asset), archive);
  fs.writeFileSync(path.join(directory, 'SHA256SUMS'), `${'0'.repeat(64)}  ${asset}\n`);
  assert.throws(() => readArtifacts(directory, '1.2.3', sha), /SHA-256/);
});
