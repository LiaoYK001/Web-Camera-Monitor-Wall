import { verifyRuntime } from '../src/runtime-integrity.mjs';
const manifest = await verifyRuntime(process.argv[2] || 'runtime');
console.log(`Verified ${manifest.files.length} Windows runtime files (${manifest.version})`);
