import { expect, test, type Page, type Request, type Route } from '@playwright/test';

/**
 * Focused regression coverage for the hardened management workflows in
 * useManagementActions/useManagementRefresh, ClientsPanel and ClusterAdmin.
 *
 * Every /api/** call is answered by an in-test fixture: no real backend, no real
 * credentials and no secret material. Two fixture switches make the interesting
 * cases explicit:
 *   holds    - the request is sent but the response never arrives.
 *   withhold - with a hold, the request never reached the server (nothing applied),
 *              which distinguishes "hung before apply" from "applied, response lost".
 */

type Surface = 'clients' | 'cluster';
type Row = Record<string, any>;
type Outcome = { status: number; json: unknown };

const seconds = () => Math.floor(Date.now() / 1000);

interface Fixture {
  users: Row[]; nodes: Row[]; volumes: Row[]; jobs: Row[];
  enrollments: Row[]; clients: Row[]; cameras: Row[];
  holds: Set<string>; withhold: Set<string>; failures: Set<string>; conflicts: Set<string>;
  held: Array<{ key: string; release: () => void }>;
  requests: string[];
}

function createFixture(): Fixture {
  return {
    users: [{ id: 'user-1', username: 'fixture-admin', enabled: true, roles: ['admin'], scopes: [], revision: 1 }],
    nodes: [{
      id: 'node-1', name: 'edge-recorder', role: 'recorder', status: 'active', version: '4.0.0-fixture',
      lastSeenAt: 1_700_000_000, clockOffsetMs: 0, certificateExpiresAt: 1_800_000_000, capabilities: {}, revision: 3,
    }],
    volumes: [{
      id: 'vol-1', nodeId: 'node-1', label: 'recordings-hot', tier: 'hot', state: 'online',
      capacityBytes: 1_000_000_000, freeBytes: 400_000_000, reserveBytes: 0, highWatermark: 0.9, lowWatermark: 0.7,
      readOnly: false, lastScrubAt: 1_700_000_000, revision: 2,
    }],
    jobs: [],
    enrollments: [{
      id: 'enroll-1', name: 'fixture-browser', platform: 'web', state: 'pending',
      createdAt: 1_700_000_000, expiresAt: seconds() + 600,
    }],
    clients: [{
      id: 'client-1', name: 'fixture-laptop', platform: 'windows', status: 'active', createdAt: 1_700_000_000,
      lastSeen: 1_700_000_000, grantExpiresAt: seconds() + 604_800, revision: 4, revokedAt: null,
      cameraCount: 1, weakRevocation: false,
    }],
    cameras: [{
      id: 'camera-1', name: 'fixture-camera', address: 'http://camera.example.invalid', adapter: 'onvif',
      credentialsRef: 'fixture-credential-ref', hardwareDecode: 'auto', capabilities: {}, health: 'online',
      profiles: [{
        id: 'main', name: 'Main', role: 'main', endpoint: '', videoCodec: 'h264', audioCodec: 'aac',
        width: 1280, height: 720, fps: 25,
      }],
      createdAt: 1_700_000_000, updatedAt: 1_700_000_000,
    }],
    holds: new Set(), withhold: new Set(), failures: new Set(), conflicts: new Set(),
    held: [], requests: [],
  };
}

/** Applies a mutation to the fixture state and returns the payload the server would send. */
function respond(fixture: Fixture, method: string, path: string, request: Request, apply: boolean): Outcome | undefined {
  if (method === 'GET') {
    switch (path) {
      case '/api/v2/users': return { status: 200, json: { users: fixture.users, revision: 1 } };
      case '/api/v2/roles': return { status: 200, json: { roles: [
        { id: 'admin', permissions: ['*'] }, { id: 'operator', permissions: ['media.view', 'media.control'] },
        { id: 'viewer', permissions: ['media.view'] }, { id: 'auditor', permissions: ['audit.view'] },
        { id: 'exporter', permissions: ['export.create'] },
      ] } };
      case '/api/v2/audit': return { status: 200, json: { records: [], nextBefore: null } };
      case '/api/v2/nodes': return { status: 200, json: { nodes: fixture.nodes, revision: 1 } };
      case '/api/v2/storage-volumes': return { status: 200, json: { volumes: fixture.volumes, revision: 1 } };
      case '/api/v2/resource-capacity': return { status: 200, json: { nodes: [{
        nodeId: 'node-1', cpuCores: 8, memoryBytes: 17_179_869_184, rated: true, capabilities: [],
        reservations: [], updatedAt: seconds(),
      }], taskPriorities: {}, referenceTiers: {}, revision: 1 } };
      case '/api/v2/recording-placements': return { status: 200, json: { placements: [], revision: 1 } };
      case '/api/v2/recordings/timeline': return { status: 200, json: {
        fromUtcMs: 0, toUtcMs: 0, storageTimeZone: 'UTC', queryDurationMs: 0, revision: 1, cameras: [],
      } };
      case '/api/v2/archive-targets': return { status: 200, json: { targets: [], revision: 1 } };
      case '/api/v2/backup-jobs': return { status: 200, json: { jobs: fixture.jobs, revision: 1 } };
      case '/api/v2/providers': return { status: 200, json: { providers: [], revision: 1 } };
      case '/api/v2/enrollments': return { status: 200, json: { enrollments: fixture.enrollments } };
      case '/api/v2/clients': return { status: 200, json: { clients: fixture.clients } };
      case '/api/v1/cameras': return { status: 200, json: { cameras: fixture.cameras } };
      default: return undefined;
    }
  }
  if (method === 'POST' && path === '/api/v2/users') {
    const body = request.postDataJSON() as Row;
    const created = {
      id: 'user-' + (fixture.users.length + 1), username: body.username, enabled: true,
      roles: body.roles, scopes: body.scopes, revision: 1,
    };
    if (apply) fixture.users = [...fixture.users, created];
    return { status: 200, json: created };
  }
  if (method === 'POST' && path === '/api/v2/node-enrollments') {
    return { status: 200, json: { id: 'reg-1', token: 'fixture-one-time-value', expiresAt: seconds() + 600, state: 'pending' } };
  }
  if (method === 'POST' && path === '/api/v2/backup-jobs') {
    const job = { id: 'job-' + (fixture.jobs.length + 1), state: 'queued', targetId: 'local', sha256: '', createdAt: Date.now(), completedAt: 0, errorCode: '' };
    if (apply) fixture.jobs = [job, ...fixture.jobs];
    return { status: 200, json: job };
  }
  const nodeEnrollment = /^\/api\/v2\/node-enrollments\/([^/]+)\/approve$/.exec(path);
  if (method === 'POST' && nodeEnrollment) {
    return { status: 200, json: { id: nodeEnrollment[1], nodeId: 'node-2', state: 'approved' } };
  }
  const node = /^\/api\/v2\/nodes\/([^/]+)$/.exec(path);
  if (method === 'DELETE' && node) {
    const target = fixture.nodes.find(item => item.id === node[1]);
    if (target && apply) target.status = 'revoked';
    return { status: 200, json: { id: node[1], state: 'revoked' } };
  }
  const enrollment = /^\/api\/v2\/enrollments\/([^/]+)\/approve$/.exec(path);
  if (method === 'POST' && enrollment) {
    const target = fixture.enrollments.find(item => item.id === enrollment[1]);
    if (target && apply) target.state = 'approved';
    return { status: 200, json: {
      clientId: 'client-' + enrollment[1], state: 'approved', grantExpiresAt: seconds() + 604_800, revision: 2, updated: false,
    } };
  }
  const client = /^\/api\/v2\/clients\/([^/]+)$/.exec(path);
  if (method === 'DELETE' && client) {
    const target = fixture.clients.find(item => item.id === client[1]);
    if (target && apply) { target.status = 'revoked'; target.revokedAt = seconds(); }
    return { status: 200, json: {
      clientId: client[1], status: 'revoked', revokedAt: seconds(), offlineEffectiveNoLaterThan: seconds() + 10,
      weakRevocation: false, cameraCredentialCleanup: 'complete',
    } };
  }
  const user = /^\/api\/v2\/users\/([^/]+)$/.exec(path);
  if (method === 'PATCH' && user) {
    const target = fixture.users.find(item => item.id === user[1]);
    const patch = request.postDataJSON() as Row;
    if (target && apply) { Object.assign(target, patch, { revision: target.revision + 1 }); }
    return { status: 200, json: target ?? patch };
  }
  const volume = /^\/api\/v2\/storage-volumes\/([^/]+)\/([^/]+)$/.exec(path);
  if (method === 'PATCH' && volume) {
    const target = fixture.volumes.find(item => item.nodeId === volume[1] && item.id === volume[2]);
    const patch = request.postDataJSON() as Row;
    if (target && apply) { Object.assign(target, patch, { revision: target.revision + 1 }); }
    return { status: 200, json: { ...(target ?? {}), ...patch } };
  }
  return undefined;
}

async function installRoutes(page: Page, fixture: Fixture) {
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const key = request.method() + ' ' + path;
    fixture.requests.push(key);
    if (fixture.failures.has(key))
      return route.fulfill({ status: 503, json: { error: { code: 'fixture-unavailable', message: 'fixture endpoint unavailable' } } });
    if (fixture.conflicts.has(key))
      return route.fulfill({ status: 409, json: { error: { code: 'revision-conflict', message: 'fixture revision conflict' } } });
    const outcome = respond(fixture, request.method(), path, request, !fixture.withhold.has(key))
      ?? { status: 404, json: { error: { code: 'fixture-endpoint-missing', message: 'no fixture handler for ' + key } } };
    if (fixture.holds.has(key)) {
      // The server did its work (unless withheld) and the response is lost in transit.
      fixture.held.push({ key, release: () => void route.fulfill({ status: outcome.status, json: outcome.json }) });
      return;
    }
    return route.fulfill({ status: outcome.status, json: outcome.json });
  });
}

async function open(page: Page, surface: Surface, fixture: Fixture) {
  // The dev server pushes a full page reload for any watched file change. This harness
  // owns no other WebSocket, so keeping that channel open (without forwarding messages)
  // guarantees one page load per workflow instead of an unrelated edit restarting it.
  await page.routeWebSocket(/.*/, () => undefined);
  await page.addInitScript(() => {
    const state = { result: true, calls: [] as string[] };
    Object.defineProperty(window, '__managementConfirm', { value: state, configurable: true });
    window.confirm = (message?: string) => { state.calls.push(String(message ?? '')); return state.result; };
  });
  await installRoutes(page, fixture);
  await page.goto('/tests/harness/management.html?surface=' + surface);
  await expect(page.getByRole('heading', { name: surface === 'clients' ? '本地客户端与授权' : '集群、权限与灾备' })).toBeVisible();
}

const count = (fixture: Fixture, key: string) => fixture.requests.filter(item => item === key).length;
const mutations = (fixture: Fixture, method: string, path: string) => count(fixture, method + ' ' + path);
const confirmState = (page: Page) => page.evaluate(() => (window as any).__managementConfirm as { result: boolean; calls: string[] });
const setConfirm = (page: Page, result: boolean) => page.evaluate(value => { (window as any).__managementConfirm.result = value; }, result);
const canLeave = (page: Page) => page.evaluate(() => window.dispatchEvent(new Event('webobs:before-navigate', { cancelable: true })));
const unloadBlocked = (page: Page) => page.evaluate(() => {
  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
});
const releaseHeld = (fixture: Fixture) => { fixture.held.splice(0).forEach(held => held.release()); };
/** React keeps the same DOM node after disabled is set; a stale click must still be rejected by the lock. */
const forceClick = (page: Page, label: string) => page.evaluate((text) => {
  const button = [...document.querySelectorAll('button')].find(item => item.textContent?.trim() === text);
  button?.removeAttribute('disabled');
  button?.click();
}, label);

async function prepareApproval(page: Page) {
  const card = page.locator('.enrollment-card');
  await card.getByLabel('配对码').fill('12345678');
  await card.getByRole('checkbox').first().check();
  return card;
}

test('clients: repeating one approval during a slow POST sends exactly one request and locks the button', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const fixture = createFixture();
  await open(page, 'clients', fixture);
  const card = await prepareApproval(page);
  fixture.holds.add('POST /api/v2/enrollments/enroll-1/approve');
  const approve = card.getByRole('button', { name: '批准并签发' });
  await approve.click();
  await expect(approve).toBeDisabled();
  await expect(card.getByLabel('配对码')).toBeDisabled();
  await expect(page.getByRole('status').filter({ hasText: '批准并签发处理中…' })).toBeVisible();
  await forceClick(page, '批准并签发');
  await page.waitForTimeout(300);
  await expect(page.getByRole('status').filter({ hasText: '批准并签发处理中…' })).toBeVisible();
  expect(mutations(fixture, 'POST', '/api/v2/enrollments/enroll-1/approve')).toBe(1);
  releaseHeld(fixture);
  await expect(page.getByRole('status').filter({ hasText: '已批准' })).toBeVisible();
  await expect(page.locator('.enrollment-card')).toHaveCount(0);
  expect(mutations(fixture, 'POST', '/api/v2/enrollments/enroll-1/approve')).toBe(1);
  expect(errors).toEqual([]);
});

test('cluster: repeating create user during a slow POST sends exactly one request and disables the form', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const fixture = createFixture();
  await open(page, 'cluster', fixture);
  await page.getByLabel('用户名').fill('fixture-new-user');
  await page.getByLabel('临时密码').fill('fixture-password-not-real');
  fixture.holds.add('POST /api/v2/users');
  const create = page.getByRole('button', { name: '创建用户' });
  await create.click();
  await expect(create).toBeDisabled();
  await expect(page.getByLabel('用户名')).toBeDisabled();
  await expect(page.getByRole('status').filter({ hasText: '创建用户处理中…' })).toBeVisible();
  await forceClick(page, '创建用户');
  await page.waitForTimeout(300);
  expect(mutations(fixture, 'POST', '/api/v2/users')).toBe(1);
  releaseHeld(fixture);
  await expect(page.getByRole('status').filter({ hasText: '用户已创建' })).toBeVisible();
  await expect(page.locator('[aria-label="用户权限 fixture-new-user"]')).toBeVisible();
  expect(mutations(fixture, 'POST', '/api/v2/users')).toBe(1);
  expect(errors).toEqual([]);
});

test('cluster: a hung create user stays unconfirmed, offers read-only reconciliation and is never retried', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'cluster', fixture);
  await page.clock.install();
  await page.getByLabel('用户名').fill('fixture-hung-user');
  await page.getByLabel('临时密码').fill('fixture-password-not-real');
  fixture.holds.add('POST /api/v2/users');
  fixture.withhold.add('POST /api/v2/users');
  await page.getByRole('button', { name: '创建用户' }).click();
  await expect.poll(() => mutations(fixture, 'POST', '/api/v2/users')).toBe(1);
  await page.clock.runFor(20_050);
  await expect(page.getByRole('alert').filter({ hasText: '创建用户结果尚未确认' })).toContainText('勿重复提交');
  const reconcile = page.getByRole('button', { name: '只读核对结果' });
  await expect(reconcile).toBeVisible();
  await page.clock.runFor(60_000);
  expect(mutations(fixture, 'POST', '/api/v2/users')).toBe(1);
  const reads = count(fixture, 'GET /api/v2/users');
  await reconcile.click();
  await expect(page.getByRole('alert').filter({ hasText: '仍未查到该用户名' })).toBeVisible();
  expect(count(fixture, 'GET /api/v2/users')).toBeGreaterThan(reads);
  await page.clock.runFor(60_000);
  expect(mutations(fixture, 'POST', '/api/v2/users')).toBe(1);
  await expect(page.locator('[aria-label="用户权限 fixture-hung-user"]')).toHaveCount(0);
});

test('clients: a lost approval response is confirmed by the read-only reconcile without re-posting', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'clients', fixture);
  await prepareApproval(page);
  await page.clock.install();
  // The server applied the approval; only the response is lost.
  fixture.holds.add('POST /api/v2/enrollments/enroll-1/approve');
  await page.getByRole('button', { name: '批准并签发' }).click();
  // Establish server application before advancing the browser's deadline: a
  // fast virtual clock may otherwise cancel fetch before routing sees it.
  await expect.poll(() => mutations(fixture, 'POST', '/api/v2/enrollments/enroll-1/approve')).toBe(1);
  await page.clock.runFor(20_050);
  await expect(page.getByRole('alert').filter({ hasText: '批准并签发结果尚未确认' })).toBeVisible();
  const reads = count(fixture, 'GET /api/v2/enrollments');
  await page.getByRole('button', { name: '只读核对结果' }).click();
  await expect(page.getByRole('status').filter({ hasText: '已确认该 enrollment 为 approved' })).toBeVisible();
  await expect(page.getByRole('button', { name: '只读核对结果' })).toHaveCount(0);
  await expect(page.locator('.enrollment-card')).toHaveCount(0);
  expect(count(fixture, 'GET /api/v2/enrollments')).toBeGreaterThan(reads);
  expect(mutations(fixture, 'POST', '/api/v2/enrollments/enroll-1/approve')).toBe(1);
  await page.clock.runFor(60_000);
  expect(mutations(fixture, 'POST', '/api/v2/enrollments/enroll-1/approve')).toBe(1);
});

test('clients: a lost revoke response is confirmed read-only and never re-sent', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'clients', fixture);
  await setConfirm(page, true);
  await page.clock.install();
  fixture.holds.add('DELETE /api/v2/clients/client-1');
  await page.getByRole('button', { name: '撤销' }).click();
  await expect(page.getByRole('status').filter({ hasText: '撤销客户端处理中…' })).toBeVisible();
  await expect.poll(() => mutations(fixture, 'DELETE', '/api/v2/clients/client-1')).toBe(1);
  await page.clock.runFor(20_050);
  await expect(page.getByRole('alert').filter({ hasText: '撤销客户端结果尚未确认' })).toBeVisible();
  await page.getByRole('button', { name: '只读核对结果' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '撤销客户端结果尚未确认' })).toHaveCount(0);
  await expect(page.locator('.client-list')).toContainText('revoked');
  expect(mutations(fixture, 'DELETE', '/api/v2/clients/client-1')).toBe(1);
  await page.clock.runFor(60_000);
  expect(mutations(fixture, 'DELETE', '/api/v2/clients/client-1')).toBe(1);
});

test('cluster: a node enrollment is created once and a hung approval is reconciled read-only', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'cluster', fixture);
  await page.getByLabel('节点名称').fill('edge-worker-2');
  await page.getByRole('button', { name: '生成注册令牌' }).click();
  await expect(page.locator('.one-time-secret')).toContainText('fixture-one-time-value');
  expect(mutations(fixture, 'POST', '/api/v2/node-enrollments')).toBe(1);
  await page.clock.install();
  fixture.holds.add('POST /api/v2/node-enrollments/reg-1/approve');
  const approve = page.getByRole('button', { name: '批准已提交 CSR' });
  await approve.click();
  await expect(approve).toBeDisabled();
  await expect.poll(() => mutations(fixture, 'POST', '/api/v2/node-enrollments/reg-1/approve')).toBe(1);
  await page.clock.runFor(20_050);
  await expect(page.getByRole('alert').filter({ hasText: '批准节点结果尚未确认' })).toBeVisible();
  await expect(approve).toBeDisabled();
  await page.getByRole('button', { name: '只读核对结果' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '没有可查询的请求关联标识' })).toBeVisible();
  await page.clock.runFor(60_000);
  expect(mutations(fixture, 'POST', '/api/v2/node-enrollments/reg-1/approve')).toBe(1);
  expect(mutations(fixture, 'POST', '/api/v2/node-enrollments')).toBe(1);
});

test('cluster: a hung backup stays unconfirmed, lists candidates and is not submitted again', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'cluster', fixture);
  await page.clock.install();
  fixture.holds.add('POST /api/v2/backup-jobs');
  await page.getByRole('button', { name: '立即备份' }).click();
  await expect.poll(() => mutations(fixture, 'POST', '/api/v2/backup-jobs')).toBe(1);
  await page.clock.runFor(20_050);
  await expect(page.getByRole('alert').filter({ hasText: '创建备份结果尚未确认' })).toBeVisible();
  await page.getByRole('button', { name: '只读核对结果' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '备份结果仍未确认' })).toContainText('job-1');
  await page.clock.runFor(60_000);
  expect(mutations(fixture, 'POST', '/api/v2/backup-jobs')).toBe(1);
});

test('cluster: a node revoke revision conflict is surfaced and cleared by refreshing the latest state', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'cluster', fixture);
  await setConfirm(page, true);
  fixture.conflicts.add('DELETE /api/v2/nodes/node-1');
  await page.getByRole('button', { name: '撤销节点' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '撤销节点发生 revision / 状态冲突' })).toContainText('草稿已保留');
  await expect(page.getByRole('button', { name: '撤销节点' })).toBeDisabled();
  const reads = count(fixture, 'GET /api/v2/nodes');
  await page.getByRole('button', { name: '刷新并确认最新状态' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '撤销节点发生 revision / 状态冲突' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '撤销节点' })).toBeEnabled();
  expect(count(fixture, 'GET /api/v2/nodes')).toBeGreaterThan(reads);
  expect(mutations(fixture, 'DELETE', '/api/v2/nodes/node-1')).toBe(1);
});

test('clients: an approval revision conflict keeps the draft and clears after refreshing', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'clients', fixture);
  const card = await prepareApproval(page);
  fixture.conflicts.add('POST /api/v2/enrollments/enroll-1/approve');
  await page.getByRole('button', { name: '批准并签发' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '批准并签发发生 revision / 状态冲突' })).toBeVisible();
  await expect(page.getByRole('button', { name: '批准并签发' })).toBeDisabled();
  await page.getByRole('button', { name: '刷新并确认最新状态' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '批准并签发发生 revision / 状态冲突' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '批准并签发' })).toBeEnabled();
  await expect(card.getByLabel('配对码')).toHaveValue('12345678');
  await expect(card.getByRole('checkbox').first()).toBeChecked();
  expect(mutations(fixture, 'POST', '/api/v2/enrollments/enroll-1/approve')).toBe(1);
});

test('cluster: one failing read keeps its last data while the other sections apply fresh results', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'cluster', fixture);
  const registry = page.locator('.admin-section').filter({ hasText: '用户与 RBAC' });
  const volumes = page.locator('.admin-section').filter({ hasText: '存储卷与资源' });
  await expect(registry).toContainText('1 users');
  await expect(page.getByText('edge-recorder')).toBeVisible();
  fixture.failures.add('GET /api/v2/nodes');
  fixture.users = [...fixture.users, { id: 'user-2', username: 'fixture-auditor', enabled: true, roles: ['auditor'], scopes: [], revision: 1 }];
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '节点读取失败或超时' })).toContainText('保留上次数据');
  await expect(registry).toContainText('2 users');
  await expect(page.getByText('fixture-auditor')).toBeVisible();
  await expect(page.getByText('edge-recorder')).toBeVisible();
  await expect(volumes).toContainText('recordings-hot');
  await expect(page.getByRole('alert')).toHaveCount(1);
  fixture.failures.delete('GET /api/v2/nodes');
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '节点读取失败或超时' })).toHaveCount(0);
});

test('clients: a hanging management read shows its own bounded error without wiping the other sections', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'clients', fixture);
  await expect(page.locator('.client-list')).toContainText('fixture-laptop');
  await page.clock.install();
  fixture.holds.add('GET /api/v2/clients');
  const initialReads = count(fixture, 'GET /api/v2/clients');
  await page.getByRole('button', { name: '刷新客户端' }).click();
  await expect.poll(() => count(fixture, 'GET /api/v2/clients')).toBeGreaterThan(initialReads);
  await page.clock.runFor(15_050);
  await expect(page.getByRole('alert').filter({ hasText: '已配对设备读取失败或超时' })).toBeVisible();
  await expect(page.locator('.enrollment-card')).toContainText('fixture-browser');
  await expect(page.locator('.enrollment-card')).toContainText('fixture-camera');
  await expect(page.locator('.client-list')).toContainText('fixture-laptop');
  await expect(page.getByRole('alert')).toHaveCount(1);
  fixture.holds.delete('GET /api/v2/clients');
  const timedOutReads = count(fixture, 'GET /api/v2/clients');
  await page.getByRole('button', { name: '刷新客户端' }).click();
  await expect.poll(() => count(fixture, 'GET /api/v2/clients')).toBeGreaterThan(timedOutReads);
  await expect(page.getByRole('alert').filter({ hasText: '已配对设备读取失败或超时' })).toHaveCount(0);
});

test('cluster: a draft or a pending mutation blocks leaving until the work is resolved', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'cluster', fixture);
  await setConfirm(page, false);
  await page.getByLabel('用户名').fill('fixture-guard-user');
  await expect.poll(() => unloadBlocked(page)).toBe(true);
  expect(await canLeave(page)).toBe(false);
  expect((await confirmState(page)).calls.at(-1)).toContain('管理草稿、一次性令牌或未确认操作仅保存在本页');
  await setConfirm(page, true);
  expect(await canLeave(page)).toBe(true);
  await page.getByLabel('临时密码').fill('fixture-password-not-real');
  fixture.holds.add('POST /api/v2/users');
  await page.getByRole('button', { name: '创建用户' }).click();
  await expect(page.getByRole('button', { name: '创建用户' })).toBeDisabled();
  expect(await canLeave(page)).toBe(false);
  await expect(page.getByRole('status').filter({ hasText: '正在保存，请稍候再切换页面' })).toBeVisible();
  releaseHeld(fixture);
  await expect(page.getByRole('status').filter({ hasText: '用户已创建' })).toBeVisible();
  await expect.poll(() => unloadBlocked(page)).toBe(false);
  expect(await canLeave(page)).toBe(true);
});

test('clients: the workspace guard holds a pairing draft until the draft is abandoned', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'clients', fixture);
  await setConfirm(page, false);
  const card = page.locator('.enrollment-card');
  await card.getByRole('checkbox').first().check();
  await expect.poll(() => unloadBlocked(page)).toBe(true);
  await page.getByRole('button', { name: '返回 Studio' }).click();
  await expect(page.locator('#root')).not.toHaveAttribute('data-left-workspace', 'true');
  expect((await confirmState(page)).calls.at(-1)).toContain('客户端授权草稿或未确认操作仅保存在本页');
  await card.getByRole('button', { name: '放弃此配对草稿' }).click();
  await setConfirm(page, true);
  await expect.poll(() => unloadBlocked(page)).toBe(false);
  await page.getByRole('button', { name: '返回 Studio' }).click();
  await expect(page.locator('#root')).toHaveAttribute('data-left-workspace', 'true');
});

test('cluster: the user and volume editors keep drafts through conflict and unconfirmed saves', async ({ page }) => {
  const fixture = createFixture();
  await open(page, 'cluster', fixture);
  const userCard = page.locator('[aria-label="用户权限 fixture-admin"]');
  await userCard.getByRole('checkbox', { name: 'operator' }).check();
  fixture.conflicts.add('PATCH /api/v2/users/user-1');
  await userCard.getByRole('button', { name: '保存权限' }).click();
  await expect(userCard).toContainText('revision 冲突：服务器为 1，草稿基于 1');
  await expect(userCard).toContainText('保存权限发生 revision / 状态冲突');
  await expect(userCard.getByRole('checkbox', { name: 'operator' })).toBeChecked();
  await userCard.getByRole('button', { name: '放弃草稿并载入服务器值' }).click();
  await expect(userCard).not.toContainText('revision 冲突');
  await expect(userCard.getByRole('checkbox', { name: 'operator' })).not.toBeChecked();
  expect(mutations(fixture, 'PATCH', '/api/v2/users/user-1')).toBe(1);

  const volumeCard = page.locator('[aria-label="存储卷设置 recordings-hot"]');
  await page.clock.install();
  await volumeCard.getByRole('combobox').selectOption('degraded');
  fixture.holds.add('PATCH /api/v2/storage-volumes/node-1/vol-1');
  await volumeCard.getByRole('button', { name: '保存存储卷' }).click();
  await expect(volumeCard.getByRole('button', { name: '保存存储卷' })).toBeDisabled();
  await expect.poll(() => mutations(fixture, 'PATCH', '/api/v2/storage-volumes/node-1/vol-1')).toBe(1);
  await page.clock.runFor(20_050);
  await expect(volumeCard).toContainText('修改存储卷结果尚未确认');
  await expect(volumeCard.getByRole('button', { name: '保存存储卷' })).toBeDisabled();
  await volumeCard.getByRole('button', { name: '只读核对存储卷' }).click();
  await expect(volumeCard).not.toContainText('结果尚未确认');
  await expect(volumeCard.getByRole('combobox')).toHaveValue('degraded');
  expect(mutations(fixture, 'PATCH', '/api/v2/storage-volumes/node-1/vol-1')).toBe(1);
  await page.clock.runFor(60_000);
  expect(mutations(fixture, 'PATCH', '/api/v2/storage-volumes/node-1/vol-1')).toBe(1);
});
