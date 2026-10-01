import net from 'node:net';
import dgram from 'node:dgram';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { atomicJson } from './settings.mjs';
export const serviceKeys = ['camera', 'events', 'clients', 'cluster', 'nvr', 'rtsp', 'gatewayApi', 'whep', 'iceTcp', 'iceUdp', 'go2rtcApi', 'go2rtcRtsp', 'go2rtcWebrtc'];
export async function bindPort(port, udp = false, address = '127.0.0.1') {
  const socket = udp ? dgram.createSocket('udp4') : net.createServer();
  return new Promise((resolve,reject) => {
    socket.once('error', error => { try { socket.close(); } catch {} reject(new Error(`Port ${port || '(automatic)'} is unavailable (${error.code}). Close the conflicting application or choose another port.`)); });
    const done = () => resolve({ port: socket.address().port, release: () => new Promise(r => socket.close(r)) });
    if (udp) socket.bind(port, address, done); else socket.listen({ port, host: address, exclusive: true }, done);
  });
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
      const lease = await bindPort(previous || 0, udp, lan && (udp || key === 'iceTcp') ? '0.0.0.0' : '127.0.0.1');
      held.push(lease); ports[key] = lease.port;
      if (key === 'go2rtcWebrtc') held.push(await bindPort(lease.port, true));
    }
    await atomicJson(path.join(root, 'ports.json'), ports);
    return ports;
  } finally { await Promise.all(held.map(item => item.release())); }
}
