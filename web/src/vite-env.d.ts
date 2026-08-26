/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

declare const __WEBOBS_BUILD_VERSION__: string;

interface TrustedTypePolicyOptions {
  createHTML?: (input: string) => string;
  createScript?: (input: string) => string;
  createScriptURL?: (input: string) => string;
}

interface TrustedTypePolicyFactory {
  createPolicy(name: string, options: TrustedTypePolicyOptions): unknown;
}

interface Window {
  trustedTypes?: TrustedTypePolicyFactory;
}
