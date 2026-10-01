import os from 'node:os';
export function privateIPv4(address) {
  const parts = address.split('.').map(Number);
  return parts.length === 4 && parts.every(p => Number.isInteger(p) && p >= 0 && p <= 255) &&
    (parts[0] === 10 || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) || (parts[0] === 192 && parts[1] === 168));
}
export function lanAddresses() {
  return [...new Set(Object.values(os.networkInterfaces()).flat().filter(item => item && !item.internal && item.family === 'IPv4' && privateIPv4(item.address)).map(item => item.address))];
}
export function caddyConfiguration(addresses, port, controlPort, storage) {
  if (!addresses.length || addresses.some(ip => !privateIPv4(ip))) throw new Error('No private LAN address is available');
  return {
    admin: { disabled: true }, storage: { module: 'file_system', root: storage },
    apps: {
      pki: { certificate_authorities: { local: { name: 'WebOBS Local CA', install_trust: false } } },
      tls: { certificates: { automate: addresses }, automation: { policies: [{ subjects: addresses, issuers: [{ module: 'internal' }] }] } },
      http: { servers: { lan: { listen: addresses.map(ip => `${ip}:${port}`), automatic_https: { disable_redirects: true },
        routes: [{ match: [{ host: addresses }], handle: [{ handler: 'reverse_proxy', upstreams: [{ dial: `127.0.0.1:${controlPort}` }],
          headers: { request: { delete: ['X-WebObs-Principal', 'X-WebObs-Permissions', 'X-WebObs-User', 'Authorization-Internal'] } } }] }] } } },
    },
  };
}
export function firewallInstructions(port, iceTcp, iceUdp, addresses, go2rtcWebrtc) {
  if (![port,iceTcp,iceUdp,...(go2rtcWebrtc===undefined?[]:[go2rtcWebrtc])].every(p => Number.isInteger(p) && p >= 1024 && p <= 65535) || addresses.some(ip => !privateIPv4(ip))) throw new Error('Invalid firewall configuration');
  // Display only; the administrator chooses whether to execute the commands.
  return [
    `New-NetFirewallRule -DisplayName 'WebOBS LAN HTTPS' -Direction Inbound -Action Allow -Profile Private -LocalAddress ${addresses.join(',')} -Protocol TCP -LocalPort ${port} -RemoteAddress LocalSubnet`,
    `New-NetFirewallRule -DisplayName 'WebOBS LAN media TCP' -Direction Inbound -Action Allow -Profile Private -Protocol TCP -LocalPort ${iceTcp} -RemoteAddress LocalSubnet`,
    `New-NetFirewallRule -DisplayName 'WebOBS LAN media UDP' -Direction Inbound -Action Allow -Profile Private -Protocol UDP -LocalPort ${iceUdp} -RemoteAddress LocalSubnet`,
    ...(go2rtcWebrtc===undefined?[]:['TCP','UDP'].map(protocol=>`New-NetFirewallRule -DisplayName 'WebOBS LAN go2rtc ${protocol}' -Direction Inbound -Action Allow -Profile Private -Protocol ${protocol} -LocalPort ${go2rtcWebrtc} -RemoteAddress LocalSubnet`)),
  ];
}
