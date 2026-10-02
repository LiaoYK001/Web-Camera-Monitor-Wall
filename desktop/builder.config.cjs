const fs = require('node:fs');
const path = require('node:path');
const official = process.env.WEBOBS_RELEASE_BUILD === 'true';
const version = process.env.WEBOBS_DESKTOP_VERSION || require('./package.json').version;
const suffix = official ? '' : '-DEVELOPMENT-UNSIGNED';
const installerName = `WebOBS-${version}-windows-x64${suffix}.exe`;
module.exports = {
  appId: 'org.webobs.desktop', productName: 'WebOBS',
  asar: true, directories: { output: process.env.WEBOBS_DESKTOP_VERSION ? `out/${process.env.WEBOBS_DESKTOP_VERSION}` : 'out', buildResources: 'assets' },
  files: ['src/**', 'assets/**', 'package.json'],
  extraResources: [{ from: 'runtime', to: 'runtime' }],
  artifactName: `WebOBS-\${version}-windows-x64${suffix}.\${ext}`,
  forceCodeSigning: official,
  publish: [{ provider: 'github', owner: 'LiaoYK001', repo: 'Web-Camera-Monitor-Wall', releaseType: 'release', private: false,
    channel: process.env.WEBOBS_RELEASE_BUILD === 'true' ? 'latest' : 'dev' }],
  electronUpdaterCompatibility: '>=6.8.9',
  electronFuses: { runAsNode: false, enableNodeOptionsEnvironmentVariable: false, enableNodeCliInspectArguments: false, onlyLoadAppFromAsar: true, enableEmbeddedAsarIntegrityValidation: true },
  win: { target: [{ target: 'nsis', arch: ['x64'] }], requestedExecutionLevel: 'asInvoker',
    // Sign the main app and NSIS installer, preserving every inventoried runtime byte.
    // Positive names override the negative suffix in electron-builder 26.
    // signIf also filters main/NSIS executables, so excluding every .exe skips them.
    signExts: ['WebOBS.exe', installerName, installerName.slice(0,-3)+'__uninstaller.exe', '!.exe'],
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
    if (official) {
      const { verifyPublisher } = await import('./src/signature.mjs');
      const error = await verifyPublisher([process.env.WEBOBS_SIGNING_PUBLISHER], path.join(context.appOutDir,'WebOBS.exe'));
      if (error !== null) throw new Error(`Desktop executable signature validation failed: ${error}`);
    }
  },
};
