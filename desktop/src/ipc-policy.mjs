export function trustedFrame(event, origin, knownContents, diagnosticUrl) {
  if(!knownContents.has(event.sender.id) || !event.senderFrame || event.senderFrame !== event.sender.mainFrame) return false;
  try {
    const url=new URL(event.senderFrame.url);
    return diagnosticUrl === url.href || (url.origin===origin && url.pathname==='/' && !url.search);
  } catch {return false;}
}
export function projectorOptions(options, displays) {
  if(!options || typeof options!=='object' || Array.isArray(options) || Object.keys(options).some(key=>!['sceneId','mode','displayId','fullscreen'].includes(key)))throw new Error('Invalid projector options');
  if(!['direct','composite'].includes(options.mode) || (options.sceneId!==undefined && !/^[A-Za-z0-9._-]{1,128}$/.test(options.sceneId)))throw new Error('Invalid scene');
  if(options.displayId!==undefined && (!Number.isInteger(options.displayId) || !displays.some(display=>display.id===options.displayId)))throw new Error('Display is unavailable');
  if(options.fullscreen!==undefined && typeof options.fullscreen!=='boolean')throw new Error('Invalid fullscreen option');
  return options;
}
