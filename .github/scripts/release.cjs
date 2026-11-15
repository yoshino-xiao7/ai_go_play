// Runs only on reviewed main, after an owner-triggered workflow_dispatch.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { route, reviewed } = require('./pr-policy.cjs');
const config = require('../governance.json');
function assertReleaseInputs(env) {
  if (env.GITHUB_REPOSITORY !== config.repository || env.GITHUB_REF !== 'refs/heads/main' ||
      env.GITHUB_ACTOR !== config.owner || env.RELEASE_CONFIRM !== 'true' ||
      !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(env.RELEASE_VERSION || '') ||
      !/^[1-9]\d*$/.test(env.RELEASE_PR || '') || !/^[a-f0-9]{40}$/.test(env.GITHUB_SHA || '')) {
    throw new Error('Only the owner may release from main, with an explicit version, release PR and confirmation.');
  }
}
function readArtifacts(directory, version, sha) {
  const manifestBytes = fs.readFileSync(path.join(directory, 'release-manifest.json'));
  const manifest = JSON.parse(manifestBytes.toString('utf8'));
  if (manifest.version !== version || manifest.commit !== sha || manifest.model_weights_included !== false ||
      manifest.asset !== `ai-go-play-v${version}.zip`) throw new Error('Artifact manifest does not match the release.');
  const archive = fs.readFileSync(path.join(directory, manifest.asset));
  const sums = fs.readFileSync(path.join(directory, 'SHA256SUMS'));
  const digest = crypto.createHash('sha256').update(archive).digest('hex');
  if (archive.length !== manifest.size || digest !== manifest.sha256 ||
      sums.toString('utf8').trim() !== `${digest}  ${manifest.asset}`) throw new Error('Artifact size or SHA-256 mismatch; publication refused.');
  return [{ name: manifest.asset, bytes: archive }, { name: 'SHA256SUMS', bytes: sums }, { name: 'release-manifest.json', bytes: manifestBytes }];
}
async function main() {
  const version = process.env.RELEASE_VERSION;
  const number = process.env.RELEASE_PR;
  const sha = process.env.GITHUB_SHA;
  assertReleaseInputs(process.env);
  const api = async (method, suffix, body) => {
    const r = await fetch(`https://api.github.com/repos/${config.repository}${suffix}`, {
      method, headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept:'application/vnd.github+json', 'Content-Type':'application/json', 'X-GitHub-Api-Version':'2022-11-28' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) { const e=new Error(`GitHub ${method}: HTTP ${r.status}`);e.status=r.status;throw e; }
    return r.json();
  };
  const all = async suffix => {
    const rows=[];
    for(let page=1;;page++) { const batch=await api('GET',`${suffix}?per_page=100&page=${page}`);rows.push(...batch);if(batch.length<100)return rows; }
  };
  const current = await api('GET','/git/ref/heads/main');
  if(current.object.sha!==sha)throw new Error('main moved since this workflow started; run again for the current release commit.');
  const pr = await api('GET',`/pulls/${number}`), decision=route(pr);
  if(!decision.ok || !decision.release || decision.version!==version || !pr.merged ||
     pr.merged_by?.login!==config.owner || pr.merge_commit_sha!==sha)throw new Error('Release must match the owner-merged integration → main PR and its exact merge commit.');
  if(!reviewed(pr,await all(`/issues/${number}/comments`),await all(`/pulls/${number}/reviews`),decision))throw new Error('Missing current owner version/SHA confirmation.');
  if(fs.readFileSync('VERSION','utf8').trim()!==version)throw new Error('Input version differs from the reviewed VERSION file.');
  const checks=(await api('GET',`/commits/${sha}/check-runs?check_name=quality&filter=latest&per_page=100`)).check_runs;
  if(!checks.some(c=>c.name==='quality' && c.app?.slug==='github-actions' && c.conclusion==='success'))throw new Error('Wait for the quality check on this main commit to succeed.');
  const tag=`v${version}`;
  if((await all('/releases')).some(r=>r.tag_name===tag))throw new Error('A release or draft already uses this version. Never overwrite a published version.');
  try { await api('GET',`/git/ref/tags/${tag}`);throw new Error('Tag already exists; choose a new release version.'); }
  catch(e){if(e.status!==404)throw e;}
  if(process.argv.includes('--validate')){console.log('Owner, version, release PR, merge commit and CI verified.');return;}
  const directory=path.resolve('.qa/release-dist');
  const artifacts=readArtifacts(directory,version,sha);
  const changelog=fs.readFileSync('CHANGELOG.md','utf8');
  const start=changelog.indexOf(`## [${version}] - `);
  if(start<0)throw new Error('Versioned release notes are missing.');
  const end=changelog.indexOf('\n## ',start+1);
  const notes=changelog.slice(start,end<0?undefined:end);
  // Upload to a draft first; a partial upload must never become a published release.
  const release=await api('POST','/releases',{tag_name:tag,target_commitish:sha,name:tag,body:notes,draft:true,prerelease:false});
  for(const {name,bytes} of artifacts){
    const url=new URL(release.upload_url.split('{')[0]);
    if(url.hostname!=='uploads.github.com')throw new Error('Unexpected artifact upload host');
    url.searchParams.set('name',name);
    const r=await fetch(url,{method:'POST',headers:{Authorization:`Bearer ${process.env.GITHUB_TOKEN}`,'Content-Type':name.endsWith('.zip')?'application/zip':'application/octet-stream'},body:bytes});
    if(!r.ok)throw new Error(`Artifact upload failed (HTTP ${r.status}); draft retained for inspection.`);
  }
  if((await api('GET','/git/ref/heads/main')).object.sha!==sha)throw new Error('main moved; draft retained, publication refused.');
  await api('PATCH',`/releases/${release.id}`,{draft:false,make_latest:'true'});
  console.log(`Published ${tag} at reviewed commit ${sha}.`);
}
module.exports={assertReleaseInputs,readArtifacts};
if(require.main===module)main().catch(e=>{console.error(e.message);process.exitCode=1;});
