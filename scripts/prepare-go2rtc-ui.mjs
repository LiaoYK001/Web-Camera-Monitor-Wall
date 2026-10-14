import { cpSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { patchMonacoSanitizer } from './patch-monaco-sanitizer.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'web/go2rtc-dist');
// Recreate this generated directory so obsolete development files are not shipped.
if (path.resolve(output) !== path.resolve(root, 'web', 'go2rtc-dist')) throw new Error('Unsafe generated asset path');
rmSync(output, { recursive: true, force: true });
mkdirSync(output, { recursive: true });
const packages = ['monaco-editor', 'dompurify', 'js-yaml', 'vis-network', 'qrcodejs', 'hls.js'];
for (const name of packages) {
  // Read the installed package root directly: recent Monaco exports intentionally
  // hide package.json. pnpm's direct dependency symlink still identifies the
  // complete package, including the AMD editor and worker assets.
  const packageRoot = realpathSync(path.join(root, 'web/node_modules', name));
  if (JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8')).name !== name)
    throw new Error(`Unexpected installed package: ${name}`);
  // Monaco's complete min/ tree includes its workers. esm/ and dev/ are not
  // used by the upstream UI; their deep paths also exceed NSIS rename limits.
  cpSync(packageRoot, path.join(output, 'vendor', name), { recursive: true, dereference: true,
    filter: source => name !== 'monaco-editor' || !['esm', 'dev'].includes(path.relative(packageRoot, source).split(path.sep)[0]) });
}
patchMonacoSanitizer(path.join(output, 'vendor/monaco-editor'), path.join(output, 'vendor/dompurify'));
const replacements = [
  ['https://cdn.jsdelivr.net/npm/monaco-editor@0.55.1/min', 'vendor/monaco-editor/min'],
  ['https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js', 'vendor/js-yaml/dist/js-yaml.min.js'],
  ['https://cdn.jsdelivr.net/npm/vis-network@10.0.2/standalone/umd/vis-network.min.js', 'vendor/vis-network/standalone/umd/vis-network.min.js'],
  ['https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js', 'vendor/qrcodejs/qrcode.min.js'],
  ['https://cdn.jsdelivr.net/npm/hls.js@1', 'vendor/hls.js/dist/hls.min.js'],
];
const upstream = path.join(root, 'go2rtc/go2rtc/www');
for (const filename of readdirSync(upstream)) {
  if (!/\.(html|js|json)$/.test(filename)) continue;
  let content = readFileSync(path.join(upstream, filename), 'utf8');
  for (const [remote, local] of replacements) content = content.replaceAll(remote, local);
  // Monaco workers need absolute URLs; an iframe on a subpath cannot resolve a
  // relative URL from a data: worker's location.
  content = content.replace("const monacoRoot = 'vendor/monaco-editor/min';",
    "const monacoRoot = new URL('vendor/monaco-editor/min', location.href).href;");
  if (filename === 'config.html') {
    // Adapt the generated copy only. Fail closed when upstream changes the
    // editor integration, instead of silently shipping the old early OK alert.
    const handler = /document\.getElementById\('save'\)\.addEventListener\('click', async \(\) => \{[\s\S]*?\n        \}\);/g;
    if ([...content.matchAll(handler)].length !== 1) throw new Error('Unexpected upstream config save handler');
    content = content.replace(handler, `document.getElementById('save').addEventListener('click', async () => {
            const button = document.getElementById('save');
            if (button.disabled) return;
            button.disabled = true;
            try {
                const {saveGo2rtcConfig} = await import('./webobs-config-save.js');
                await saveGo2rtcConfig(editor, dump, value => { dump = value; });
            } catch {
                alert('Unable to load the configuration editor integration. Refresh and retry.');
            } finally { button.disabled = false; }
        });`);
  }
  writeFileSync(path.join(output, filename), content);
}
cpSync(path.join(root, 'go2rtc/config-save.js'), path.join(output, 'webobs-config-save.js'));
cpSync(path.join(root, 'go2rtc/go2rtc/LICENSE'), path.join(output, 'GO2RTC-LICENSE'));
cpSync(path.join(root, 'go2rtc/dependencies.lock.json'), path.join(output, 'dependencies.lock.json'));
console.log('Prepared complete go2rtc WebUI with local third-party assets.');
