import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { createInterface } from 'node:readline';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const require = createRequire(new URL('../../web/package.json', import.meta.url));
const { _android } = require('@playwright/test');
const devices = await _android.devices();
const device = devices.find(item => item.serial() === process.env.WEBOBS_ANDROID_SERIAL);
if (!device) throw new Error('Explicit qualification device is unavailable');
device.setDefaultTimeout(10000);
for await (const line of createInterface({ input: process.stdin })) {
  try {
    const request = JSON.parse(line);
    if (request.capture) { await writeFile(join(process.env.WEBOBS_ANDROID_OUTPUT, 'native-failure.png'), await device.screenshot()); process.stdout.write('{"ok":true}\n'); continue; }
    if (request.inspect) {
      const nodes = {};
      for (const res of ['android:id/alertTitle', 'android:id/button1', 'android:id/button2']) nodes[res] = await device.info({ res }).catch(() => null);
      process.stdout.write(JSON.stringify({ ok: true, nodes }) + '\n'); continue;
    }
    // Initialize native automation without swallowing missing-driver or device
    // errors as a selector miss. The explicit owned package must be foreground.
    if (request.tap && request.resource && request.pattern === 'app_menu$')
      await device.wait({ pkg: 'io.github.liaoyk001.webobs.android.updatequalification' });
    if (!request.tap && ['允许 WebOBS 安装更新', '请先处理当前工作'].includes(request.pattern)) {
      await device.wait({ res: 'android:id/alertTitle' });
      const title = (await device.info({ res: 'android:id/alertTitle' })).text;
      if (title !== request.pattern) throw new Error('Unexpected native dialog title: ' + title);
      process.stdout.write('{"ok":true}\n'); continue;
    }
    if (request.tap && ['^(Install|Update|安装|更新)$', '^(Done|完成)$'].includes(request.pattern)) {
      let target;
      const deadline = Date.now() + 20000;
      while (!target && Date.now() < deadline) {
        const res = request.pattern === '^(Done|完成)$' ? 'android:id/button2' : 'android:id/button1';
        const candidate = await device.info({ res }).catch(() => null);
        if (candidate?.enabled && candidate.pkg === 'com.android.packageinstaller' && new RegExp(request.pattern, 'i').test(candidate.text?.trim())) target = candidate;
        if (!target) await new Promise(resolve => setTimeout(resolve, 150));
      }
      if (!target) throw new Error('Expected system installer confirmation is absent');
      const { bounds } = target;
      execFileSync(process.env.WEBOBS_ANDROID_ADB, ['-s', device.serial(), 'shell', 'input', 'tap', String(Math.round(bounds.x + bounds.width / 2)), String(Math.round(bounds.y + bounds.height / 2))], { timeout: 10000, stdio: 'pipe' });
      process.stdout.write('{"ok":true}\n'); continue;
    }
    if (request.tap && ['校验并交给系统安装', '稍后', '返回处理', '已保存，继续'].includes(request.pattern)) {
      let target;
      const deadline = Date.now() + 10000;
      while (!target && Date.now() < deadline) {
        for (const res of ['android:id/button1', 'android:id/button2']) {
          const candidate = await device.info({ res }).catch(() => null);
          if (candidate?.text?.trim() === request.pattern) { target = candidate; break; }
        }
        if (!target) await new Promise(resolve => setTimeout(resolve, 150));
      }
      if (!target) throw new Error('Expected native dialog button is absent');
      const { bounds } = target;
      execFileSync(process.env.WEBOBS_ANDROID_ADB, ['-s', device.serial(), 'shell', 'input', 'tap', String(Math.round(bounds.x + bounds.width / 2)), String(Math.round(bounds.y + bounds.height / 2))], { timeout: 10000, stdio: 'pipe' });
      process.stdout.write('{"ok":true}\n'); continue;
    }
    const selector = request.resource ? { res: new RegExp('.*' + request.pattern) } : { text: request.pattern.startsWith('^') ? new RegExp(request.pattern) : request.pattern };
    let target;
    const deadline = Date.now() + 20000;
    while (!target && Date.now() < deadline) {
      target = await device.info(selector).catch(() => null);
      if (!target) await new Promise(resolve => setTimeout(resolve, 150));
    }
    if (!target) throw new Error('Expected native element is absent: ' + request.pattern);
    const { bounds } = target;
    if (request.tap) execFileSync(process.env.WEBOBS_ANDROID_ADB, ['-s', device.serial(), 'shell', 'input', 'tap', String(Math.round(bounds.x + bounds.width / 2)), String(Math.round(bounds.y + bounds.height / 2))], { timeout: 10000, stdio: 'pipe' });
    process.stdout.write(JSON.stringify({ ok: true, bounds }) + '\n');
  } catch (error) { process.stdout.write(JSON.stringify({ ok: false, error: String(error.message).slice(0, 300) }) + '\n'); }
}
await device.close();
