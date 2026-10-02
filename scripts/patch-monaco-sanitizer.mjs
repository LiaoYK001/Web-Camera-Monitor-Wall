import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

const requireWeb = createRequire(new URL('../web/package.json', import.meta.url));
const { parse } = requireWeb('acorn');
const bundledVersion = '3.4.15';
const patchedVersion = '3.4.16';
const digest = source => createHash('sha256').update(source).digest('hex');

function visit(node, callback, ancestors = []) {
  if (!node || typeof node.type !== 'string') return;
  callback(node, ancestors);
  ancestors.push(node);
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) for (const child of value) visit(child, callback, ancestors);
    else if (value && typeof value === 'object') visit(value, callback, ancestors);
  }
  ancestors.pop();
}

function versionFactories(source, version, comments = []) {
  const tree = parse(source, { ecmaVersion: 'latest', onComment: comments });
  const factories = [];
  visit(tree, (node, ancestors) => {
    const value = node.right?.type === 'Literal' ? node.right.value :
      node.right?.type === 'TemplateLiteral' && node.right.expressions.length === 0 ?
        node.right.quasis[0].value.cooked : null;
    if (node.type !== 'AssignmentExpression' || node.left.type !== 'MemberExpression' ||
        node.left.computed || node.left.property.name !== 'version' ||
        value !== version) return;
    const owner = ancestors.findLast(parent => /Function/.test(parent.type));
    if (!owner) throw new Error('DOMPurify version is outside its factory');
    factories.push(owner);
  });
  return factories;
}

export function replaceSanitizerFactory(source, purifySource) {
  const comments = [];
  const factories = versionFactories(source, bundledVersion, comments);
  if (factories.length !== 1 || factories[0].type !== 'FunctionDeclaration' || !factories[0].id)
    throw new Error('Expected one complete pinned Monaco DOMPurify factory; review upstream changes');
  const original = factories[0];
  const purifyTree = parse(purifySource, { ecmaVersion: 'latest' });
  const statement = purifyTree.body[0]?.expression;
  const call = statement?.type === 'UnaryExpression' ? statement.argument : statement;
  const factory = call?.type === 'CallExpression' ? call.arguments[1] : null;
  if (factory?.type !== 'FunctionExpression' || factory.params.length !== 0 ||
      versionFactories(purifySource, patchedVersion).length !== 1)
    throw new Error('Expected the complete, self-contained pinned DOMPurify UMD factory');
  const license = purifySource.match(/^\/\*![\s\S]*?\*\//)?.[0];
  if (!license?.includes(`DOMPurify ${patchedVersion}`)) throw new Error('DOMPurify license/version missing');
  // Replace the whole sanitizer constructor, not individual minified statements.
  // The official UMD factory includes every helper and returns its own root factory.
  const replacement = `${license}\nfunction ${original.id.name}(...roots) {\n` +
    `const purifier = (${purifySource.slice(factory.start, factory.end)})();\n` +
    'return roots.length ? purifier(...roots) : purifier;\n}\n';
  const edits = [{ start: original.start, end: original.end, text: replacement }];
  for (const comment of comments) {
    if (comment.start >= original.start && comment.end <= original.end) continue;
    if (comment.value.includes(`DOMPurify ${bundledVersion}`))
      edits.push({ start: comment.start, end: comment.end, text: license });
  }
  let output = source;
  for (const edit of edits.sort((a, b) => b.start - a.start))
    output = output.slice(0, edit.start) + edit.text + output.slice(edit.end);
  if (versionFactories(output, bundledVersion).length || versionFactories(output, patchedVersion).length !== 1)
    throw new Error('Sanitizer replacement did not remove the old executable factory');
  return { source: output, factoryName: original.id.name };
}

export function packagedFactorySource(source, name) {
  const matches = [];
  visit(parse(source, { ecmaVersion: 'latest' }), node => {
    if (node.type === 'FunctionDeclaration' && node.id?.name === name &&
        node.body.body[0]?.type === 'VariableDeclaration' &&
        node.body.body[0].declarations[0]?.id?.name === 'purifier') matches.push(node);
  });
  if (matches.length !== 1) throw new Error('Packaged sanitizer factory is missing or ambiguous');
  return source.slice(matches[0].start, matches[0].end);
}

export function patchMonacoSanitizer(monacoRoot, purifyRoot) {
  const monaco = JSON.parse(readFileSync(path.join(monacoRoot, 'package.json'), 'utf8'));
  const purify = JSON.parse(readFileSync(path.join(purifyRoot, 'package.json'), 'utf8'));
  if (monaco.version !== '0.57.0' || purify.version !== patchedVersion)
    throw new Error('Review the sanitizer integration before changing pinned upstream versions');
  const min = path.join(monacoRoot, 'min');
  const candidates = readdirSync(min, { recursive: true }).filter(name => name.endsWith('.js'));
  const matches = [];
  for (const name of candidates) {
    const source = readFileSync(path.join(min, name), 'utf8');
    if (!source.includes(bundledVersion) || !versionFactories(source, bundledVersion).length) continue;
    matches.push({ name, source });
  }
  if (matches.length !== 1) throw new Error('Expected exactly one bundled DOMPurify module');
  const { name, source } = matches[0];
  const replacement = replaceSanitizerFactory(source, readFileSync(path.join(purifyRoot, 'dist/purify.min.js'), 'utf8'));
  writeFileSync(path.join(min, name), replacement.source);
  monaco.dependencies.dompurify = patchedVersion;
  writeFileSync(path.join(monacoRoot, 'package.json'), JSON.stringify(monaco, null, 2) + '\n');
  const evidence = {
    monacoVersion: monaco.version, dompurifyVersion: patchedVersion, replacedVersion: bundledVersion,
    file: `min/${name.split(path.sep).join('/')}`, factoryName: replacement.factoryName,
    upstreamSha256: digest(source), packagedSha256: digest(replacement.source),
  };
  writeFileSync(path.join(monacoRoot, 'webobs-sanitizer.json'), JSON.stringify(evidence, null, 2) + '\n');
  console.log(`Patched packaged Monaco ${monaco.version}: DOMPurify ${bundledVersion} -> ${patchedVersion}`);
  return evidence;
}
