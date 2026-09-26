import type { CameraAdapter } from './types';

export interface BulkSourceLine {
  line: number;
  name: string;
  url: string;
  adapter: CameraAdapter;
}

export function parseBulkSourceLines(text: string): { entries: BulkSourceLine[]; errors: string[] } {
  const entries: BulkSourceLine[] = [];
  const errors: string[] = [];
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = raw.trim();
    if (!line || line.startsWith('#')) return;
    const separator = line.indexOf('|');
    const colon = line.search(/:\s+(?=\S)/);
    const boundary = separator >= 0 ? separator : colon;
    const width = separator >= 0 ? 1 : 1;
    if (boundary < 1) { errors.push(`第 ${index + 1} 行：请用“名称 | 链接”分隔`); return; }
    const name = line.slice(0, boundary).trim();
    const url = line.slice(boundary + width).trim();
    if (!name || name.length > 128) { errors.push(`第 ${index + 1} 行：名称需为 1–128 个字符`); return; }
    let parsed: URL;
    try { parsed = new URL(url); } catch { errors.push(`第 ${index + 1} 行：链接格式无效`); return; }
    if (!parsed.hostname || !url || /[\u0000-\u001f]/.test(url)) { errors.push(`第 ${index + 1} 行：链接格式无效`); return; }
    const protocol = parsed.protocol.toLowerCase();
    let adapter: CameraAdapter;
    if (protocol === 'rtsp:' || protocol === 'rtsps:') adapter = 'rtsp';
    else if (protocol === 'https:') {
      const path = parsed.pathname.toLowerCase();
      if (path.endsWith('.m3u8')) adapter = 'hls';
      else if (path.endsWith('.flv')) adapter = 'http-flv';
      else if (/\.(mjpg|mjpeg)$/.test(path)) adapter = 'mjpeg';
      else if (/\.(jpg|jpeg|png)$/.test(path)) adapter = 'snapshot';
      else { errors.push(`第 ${index + 1} 行：HTTPS 链接类型不明确，请单独添加并探测`); return; }
    } else { errors.push(`第 ${index + 1} 行：批量导入支持 RTSP/RTSPS 和可识别类型的 HTTPS 链接`); return; }
    if ((parsed.username && !parsed.password) || (!parsed.username && parsed.password)) {
      errors.push(`第 ${index + 1} 行：链接中的账号和密码必须同时提供`); return;
    }
    entries.push({ line: index + 1, name, url, adapter });
  });
  return { entries, errors };
}
