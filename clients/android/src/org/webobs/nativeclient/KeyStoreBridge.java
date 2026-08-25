package org.webobs.nativeclient;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.os.PowerManager;

import org.qtproject.qt.android.QtNative;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

public final class KeyStoreBridge {
    private static final String ALIAS = "webobs-device-identity-v1";
    private static final String PREFS = "webobs-secure-identity";
    private static final String VALUE = "ciphertext";
    private static final byte[] AAD = "WebObs Native Device Identity v1".getBytes(StandardCharsets.UTF_8);
    private static PowerManager.WakeLock wakeLock;

    private KeyStoreBridge() {}

    private static Context context() {
        return QtNative.getContext();
    }

    static Context contextForPlatform() {
        return context();
    }

    private static KeyStore keyStore() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        return store;
    }

    private static SecretKey key(boolean create) throws Exception {
        KeyStore store = keyStore();
        if (store.containsAlias(ALIAS)) {
            return (SecretKey) store.getKey(ALIAS, null);
        }
        if (!create) {
            return null;
        }
        KeyGenerator generator = KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setUserAuthenticationRequired(false)
                .build());
        return generator.generateKey();
    }

    public static boolean available() {
        try {
            return context() != null && key(true) != null;
        } catch (Exception ignored) {
            return false;
        }
    }

    public static boolean save(String plaintext) {
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key(true));
            cipher.updateAAD(AAD);
            byte[] encrypted = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
            byte[] iv = cipher.getIV();
            byte[] combined = new byte[1 + iv.length + encrypted.length];
            combined[0] = (byte) iv.length;
            System.arraycopy(iv, 0, combined, 1, iv.length);
            System.arraycopy(encrypted, 0, combined, 1 + iv.length, encrypted.length);
            return context().getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                    .putString(VALUE, Base64.encodeToString(combined, Base64.NO_WRAP)).commit();
        } catch (Exception ignored) {
            return false;
        }
    }

    public static String load() {
        try {
            String encoded = context().getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                    .getString(VALUE, null);
            SecretKey secret = key(false);
            if (encoded == null || secret == null) {
                return null;
            }
            byte[] combined = Base64.decode(encoded, Base64.NO_WRAP);
            int ivLength = combined[0] & 0xff;
            if (ivLength < 12 || combined.length <= 1 + ivLength + 16) {
                return null;
            }
            byte[] iv = new byte[ivLength];
            byte[] encrypted = new byte[combined.length - 1 - ivLength];
            System.arraycopy(combined, 1, iv, 0, ivLength);
            System.arraycopy(combined, 1 + ivLength, encrypted, 0, encrypted.length);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, secret, new GCMParameterSpec(128, iv));
            cipher.updateAAD(AAD);
            return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
        } catch (Exception ignored) {
            return null;
        }
    }

    public static boolean clear() {
        try {
            SharedPreferences preferences = context().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            boolean removed = preferences.edit().remove(VALUE).commit();
            KeyStore store = keyStore();
            if (store.containsAlias(ALIAS)) {
                store.deleteEntry(ALIAS);
            }
            return removed;
        } catch (Exception ignored) {
            return false;
        }
    }

    public static boolean setWakeLock(boolean active) {
        try {
            if (active) {
                if (wakeLock == null) {
                    PowerManager manager = (PowerManager) context().getSystemService(Context.POWER_SERVICE);
                    wakeLock = manager.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK,
                            "WebObs:ForegroundMonitor");
                    wakeLock.setReferenceCounted(false);
                }
                if (!wakeLock.isHeld()) {
                    wakeLock.acquire();
                }
            } else if (wakeLock != null && wakeLock.isHeld()) {
                wakeLock.release();
            }
            return !active || (wakeLock != null && wakeLock.isHeld());
        } catch (Exception ignored) {
            return false;
        }
    }

    public static boolean wakeLockHeld() {
        return wakeLock != null && wakeLock.isHeld();
    }
}
