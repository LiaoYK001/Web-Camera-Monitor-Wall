// Main-process lease, independent of Chromium background timer throttling.
// The request callback supplies the authenticated session and one-boot secret.
export class NativePreviewClient {
  constructor(request, interval = 3000) {
    this.request = request;
    this.interval = interval;
    this.value = { supported: true, requested: false, state: 0, frames: 0 };
    this.pending = Promise.resolve();
    this.generation = 0;
  }
  status() { return { ...this.value }; }
  enqueue(operation) {
    const work = this.pending.catch(() => {}).then(() => this.request(operation)).then(value => {
      if (!value || value.supported !== true || typeof value.requested !== 'boolean' ||
          ![0, 1, 2, 3].includes(value.state) || !Number.isSafeInteger(value.frames) || value.frames < 0)
        throw new Error('原生监看返回无效状态，请重启本机服务。');
      return value;
    });
    this.pending = work;
    return work;
  }
  async open() {
    const generation = ++this.generation;
    clearTimeout(this.timer);
    const value = await this.enqueue('open');
    if (generation === this.generation) {
      this.value = value;
      this.schedule(generation);
    }
    return this.status();
  }
  schedule(generation) {
    this.timer = setTimeout(async () => {
      try {
        const value = await this.enqueue('status');
        if (generation !== this.generation) return;
        this.value = value;
        if (value.requested && value.state !== 3) this.schedule(generation);
      } catch {
        if (generation === this.generation)
          this.value = { ...this.value, requested: false, state: 3 };
        // No renewal after logout or failed authorization. The engine expires
        // the window even if a renderer or this main process disappears.
      }
    }, this.interval);
    this.timer.unref?.();
  }
  async close() {
    ++this.generation;
    clearTimeout(this.timer);
    this.value = { ...this.value, requested: false };
    const value = await this.enqueue('close');
    this.value = value;
    return this.status();
  }
}

export async function requestNativePreview(operation, { origin, token, cookies, fetch: send = globalThis.fetch }) {
  const methods = { open: 'POST', status: 'GET', close: 'DELETE' };
  if (!Object.hasOwn(methods, operation)) throw new Error('Invalid native preview operation');
  if (!/^http:\/\/127\.0\.0\.1:\d{1,5}$/.test(origin) || !/^[a-f0-9]{64}$/.test(token || ''))
    throw new Error('本机原生监看尚未就绪。');
  const sessionCookies = await cookies.get({ url: origin });
  const cookie = sessionCookies.map(({ name, value }) => `${name}=${value}`).join('; ');
  if (!cookie || /[\r\n]/.test(cookie)) throw new Error('请先登录本机账号。');
  const response = await send(`${origin}/api/v1/program/native-preview`, {
    method: methods[operation], signal: AbortSignal.timeout(5000), redirect: 'error',
    headers: { Origin: origin, Cookie: cookie, 'X-WebOBS-Native-Token': token },
  });
  if (!response.ok) throw new Error(response.status === 401 || response.status === 403
    ? '原生监看需要有效的本机登录与监看权限。' : '原生监看暂时不可用，请检查本机服务。');
  return response.json();
}
