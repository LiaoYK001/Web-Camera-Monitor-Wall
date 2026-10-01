const fs = require('node:fs');
const path = require('node:path');
module.exports = {
  appId: 'org.webobs.desktop', productName: 'WebOBS',
  asar: true, directories: { output: process.env.WEBOBS_DESKTOP_VERSION ? `out/${process.env.WEBOBS_DESKTOP_VERSION}` : 'out', buildResources: 'assets' },
  files: ['src/**', 'assets/**', 'package.json'],
  extraResources: [{ from: 'runtime', to: 'runtime' }],
  artifactName: 'WebOBS-${version}-windows-x64${env.WEBOBS_PACKAGE_SUFFIX}.${ext}',
  publish: [{ provider: 'github', owner: 'LiaoYK001', repo: 'Web-Camera-Monitor-Wall', releaseType: 'release', private: false }],
  electronUpdaterCompatibility: '>=6.8.9',
  electronFuses: { runAsNode: false, enableNodeOptionsEnvironmentVariable: false, enableNodeCliInspectArguments: false, onlyLoadAppFromAsar: true, enableEmbeddedAsarIntegrityValidation: true },
  win: { target: [{ target: 'nsis', arch: ['x64'] }], requestedExecutionLevel: 'asInvoker',
    signtoolOptions: { publisherName: process.env.WEBOBS_SIGNING_PUBLISHER || 'WebOBS DEVELOPMENT ONLY' } },
  nsis: { oneClick: false, perMachine: false, allowElevation: false, allowToChangeInstallationDirectory: true,
    deleteAppDataOnUninstall: false, createDesktopShortcut: true, createStartMenuShortcut: true, runAfterFinish: true },
  beforePack: async () => {
    const { verifyRuntime } = await import('./src/runtime-integrity.mjs');
    await verifyRuntime(path.resolve(__dirname, 'runtime'));
    const official = process.env.WEBOBS_RELEASE_BUILD === 'true';
    if (official && (!process.env.CSC_LINK || !process.env.WEBOBS_SIGNING_PUBLISHER))
      throw new Error('Official Windows packages require Authenticode credentials and a publisher.');
    if (!official && !(process.env.WEBOBS_DESKTOP_VERSION || require('./package.json').version).includes('-dev.'))
      throw new Error('Unsigned builds must use a -dev.* version.');
    fs.writeFileSync(path.join(__dirname, 'src', 'distribution.json'), JSON.stringify({ official, publisher: official ? process.env.WEBOBS_SIGNING_PUBLISHER : null }));
  },
  afterSign: async context => {
    const { verifyRuntime } = await import('./src/runtime-integrity.mjs');
    await verifyRuntime(path.join(context.appOutDir, 'resources', 'runtime'));
  },
};
