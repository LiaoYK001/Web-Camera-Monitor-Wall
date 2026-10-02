import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';

const executeFile = promisify(execFile);
// Signature-check errors must reject the update, including a missing or timed-out
// verifier. Use the Windows component by absolute path, never inherited PATH.
export async function verifyPublisher(publishers, file, execute = executeFile) {
  if (!Array.isArray(publishers) || !publishers.length || publishers.some(name => typeof name !== 'string' || !name || name.length > 512) || typeof file !== 'string' || !path.isAbsolute(file) || file.length > 4096) throw new Error('Invalid publisher verification input');
  const payload = Buffer.from(JSON.stringify({ file }), 'utf8').toString('base64');
  const script = `$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $inputData=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${payload}')) | ConvertFrom-Json; $signature=Get-AuthenticodeSignature -LiteralPath $inputData.file; $publisher=if($signature.SignerCertificate){$signature.SignerCertificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName,$false)}else{''}; @{status=[string]$signature.Status; publisher=$publisher; path=$signature.Path} | ConvertTo-Json -Compress`;
  const executable = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  const env = { ...process.env };
  for (const key of Object.keys(env)) if (key.toLowerCase() === 'psmodulepath') delete env[key];
  env.PSModulePath = path.join(path.dirname(executable), 'Modules');
  const { stdout, stderr } = await execute(executable, ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')], { env, windowsHide: true, timeout: 30000, maxBuffer: 65536, encoding: 'utf8' });
  if (stderr.trim()) throw new Error('Authenticode verifier failed');
  const signature = JSON.parse(stdout.replace(/^\uFEFF/, '').trim());
  if (typeof signature.path !== 'string' || path.resolve(signature.path).toLowerCase() !== path.resolve(file).toLowerCase()) throw new Error('Authenticode verifier returned a different file');
  return signature.status === 'Valid' && publishers.includes(signature.publisher) ? null : 'Installer signature or publisher does not match';
}
