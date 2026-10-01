import { cpSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const resolveWeb = createRequire(path.join(root, 'web/package.json'));
const output = path.join(root, 'web/go2rtc-dist');
mkdirSync(output, { recursive: true });
const packages = ['monaco-editor', 'js-yaml', 'vis-network', 'qrcodejs', 'hls.js'];
for (const name of packages) {
  const packageRoot = path.dirname(resolveWeb.resolve(`${name}/package.json`));
  // Preserve upstream directory structure and licenses, including Monaco workers.
  cpSync(packageRoot, path.join(output, 'vendor', name), { recursive: true, dereference: true });
}
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
  writeFileSync(path.join(output, filename), content);
}
cpSync(path.join(root, 'go2rtc/go2rtc/LICENSE'), path.join(output, 'GO2RTC-LICENSE'));
cpSync(path.join(root, 'go2rtc/dependencies.lock.json'), path.join(output, 'dependencies.lock.json'));
console.log('Prepared complete go2rtc WebUI with local third-party assets.');
