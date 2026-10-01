import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Exercise the pinned builder's real signing filter, including its signIf fallback.
const require = createRequire(realpathSync(new URL('../node_modules/electron-builder/package.json',import.meta.url)));
require('app-builder-lib');
const { WinPackager } = require('app-builder-lib/out/winPackager.js');
const configPath = fileURLToPath(new URL('../builder.config.cjs', import.meta.url));
const builder = require(configPath);

test('actual builder signs product and NSIS executables while preserving inventoried runtime bytes', () => {
  const packager = { platformSpecificBuildOptions: builder.win };
  const matches = file => WinPackager.prototype.shouldSignFile.call(packager, file, true);
  const installer = builder.win.signExts[1];
  for (const file of ['out/win-unpacked/WebOBS.exe', `out/${installer}`, `out/${installer.slice(0,-3)}__uninstaller.exe`]) assert.equal(matches(file), true, file);
  for (const file of ['resources/runtime/bin/webobsd.exe', 'resources/runtime/bin/ffmpeg.exe', 'resources/runtime/bin/go2rtc.exe', 'resources/runtime/python/python.exe', 'resources/runtime/obs-plugins/64bit/obs-browser-page.exe']) assert.equal(matches(file), false, file);
});

test('official configuration requires signatures and includes stable installer signing', () => {
  const originalOfficial = process.env.WEBOBS_RELEASE_BUILD, originalVersion = process.env.WEBOBS_DESKTOP_VERSION;
  try {
    process.env.WEBOBS_RELEASE_BUILD='true'; process.env.WEBOBS_DESKTOP_VERSION='3.4.0';
    delete require.cache[configPath];
    const official = require(configPath);
    assert.equal(official.forceCodeSigning, true);
    assert.equal(official.publish[0].channel, 'latest');
    const packager = { platformSpecificBuildOptions: official.win };
    for (const file of ['WebOBS.exe','WebOBS-3.4.0-windows-x64.exe','WebOBS-3.4.0-windows-x64.__uninstaller.exe']) assert.equal(WinPackager.prototype.shouldSignFile.call(packager,file,true),true,file);
    assert.equal(WinPackager.prototype.shouldSignFile.call(packager,'resources/runtime/bin/webobsd.exe',true),false);
  } finally {
    for (const [name,value] of [['WEBOBS_RELEASE_BUILD',originalOfficial],['WEBOBS_DESKTOP_VERSION',originalVersion]]) {
      if(value===undefined) delete process.env[name]; else process.env[name]=value;
    }
    delete require.cache[configPath];
  }
});
