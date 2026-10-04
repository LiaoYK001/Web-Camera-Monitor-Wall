import net from 'node:net';
import dgram from 'node:dgram';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { atomicJson } from './settings.mjs';
export const serviceKeys = ['camera', 'events', 'clients', 'cluster', 'nvr', 'rtsp', 'gatewayApi', 'whep', 'iceTcp', 'iceUdp', 'go2rtcApi', 'go2rtcRtsp', 'go2rtcWebrtc'];
export async function bindPort(port, udp = false, address = '127.0.0.1') {
  const socket = udp ? dgram.createSocket('udp4') : net.createServer();
  return new Promise((resolve,reject) => {
    socket.once('error', error => { try { socket.close(); } catch {} reject(Object.assign(new Error(`Port ${port || '(automatic)'} is unavailable (${error.code}). Close the conflicting application or choose another port.`), { code: error.code })); });
    const done = () => resolve({ port: socket.address().port, release: () => new Promise(r => socket.close(r)) });
    if (udp) socket.bind(port, address, done); else socket.listen({ port, host: address, exclusive: true }, done);
  });
}
export async function bindSharedPort(port = 0, address = '127.0.0.1', bind = bindPort) {
  for (let attempt = 0; attempt < 16; attempt++) {
    // UDP automatic allocation avoids the Windows UDP exclusions that a TCP
    // ephemeral choice does not account for. Both protocols stay reserved.
    const udpFirst = port === 0;
    const candidate = await bind(port, udpFirst, address);
    try {
      const other = await bind(candidate.port, !udpFirst, address);
      return udpFirst ? [other, candidate] : [candidate, other];
    }
    catch (error) {
      await candidate.release();
      // OS TCP/UDP reservations differ. Retry only first-use automatic ports;
      // saved choices must report their conflict without silently migrating.
      if (port !== 0 || !['EADDRINUSE', 'EACCES'].includes(error.code) || attempt === 15) throw error;
    }
  }
}
export async function allocatePorts(root, lan = false) {
  let saved;
  try { saved = JSON.parse(await readFile(path.join(root, 'ports.json'), 'utf8')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const held = [], ports = { control: 18080 };
  try {
    held.push(await bindPort(18080));
    for (const key of serviceKeys) {
      const previous = saved?.[key];
      if (saved && (!Number.isInteger(previous) || previous < 1024 || previous > 65535)) throw new Error('Invalid saved port allocation');
      const udp = key === 'iceUdp';
      const address = lan && (udp || key === 'iceTcp' || key === 'go2rtcWebrtc') ? '0.0.0.0' : '127.0.0.1';
      if (key === 'go2rtcWebrtc') {
        const shared = await bindSharedPort(previous || 0, address);
        held.push(...shared); ports[key] = shared[0].port;
        continue;
      }
      const lease = await bindPort(previous || 0, udp, address);
      held.push(lease); ports[key] = lease.port;
    }
    await atomicJson(path.join(root, 'ports.json'), ports);
    return ports;
  } finally { await Promise.all(held.map(item => item.release())); }
}
