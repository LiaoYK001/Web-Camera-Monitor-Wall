import * as runtime from '../../src/localRuntime';
import { queueStudioSync } from '../../src/syncRuntime';
import type { StudioDocument } from '../../src/types';

// Uses production encryption, redaction and atomic queue/profile persistence.
// Synthetic fixture grant only; NOT grant signature or device qualification.
Object.assign(window, { pwaSeed: async (studio: StudioDocument, queued: boolean) => {
  const expires = Math.floor(Date.now() / 1000) + 3600;
  const clientId = 'b'.repeat(32);
  await runtime.saveBrowserIdentity({ enrollmentId: 'a'.repeat(32), clientId,
    deviceToken: 'B'.repeat(64), signingPublicKey: 'C'.repeat(43), signingPrivateKey: 'D'.repeat(86),
    encryptionPublicKey: 'E'.repeat(43), encryptionPrivateKey: 'F'.repeat(43), expiresAt: expires * 1000,
    grantPayload: { format: 'webobs-browser-grant-v1', contractVersion: 2, clientId,
      issuedAt: expires - 3600, expiresAt: expires, revision: 1, cameras: [] },
  });
  await runtime.saveLocalConfigProfile('Saved device profile', studio);
  await runtime.saveLocalStudio(studio);
  if (queued) await queueStudioSync(studio);
}, pwaRead: async () => ({ profiles: await runtime.listLocalConfigProfiles(), queue: await runtime.loadSyncQueue() }) });
