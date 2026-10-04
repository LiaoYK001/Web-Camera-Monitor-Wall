// Synthetic account data for the browser/native large-preference boundary.
// These sources are preference identities; no media or camera is activated.
exports.largePreferenceWorkspace = (count = 1000) => ({
  schemaVersion: 5, mode: 'manual', localMonitorVolume: 1,
  audioMonitorEnabled: false, audioOutput: 'speaker',
  sourceDecorations: Object.fromEntries(Array.from({ length: count }, (_, index) => [`other-scene-${index}`, {
    telemetry: { enabled: false, fields: ['fps', 'bitrate', 'codec', 'decoder'], position: 'bottom-left',
      customX: 0, customY: 1, textOpacity: .9, backgroundEnabled: true, backgroundColor: '#000000',
      backgroundOpacity: .45, refreshIntervalMs: 1000 },
    audioMeter: { enabled: false, orientation: 'vertical', position: 'left', size: 1, opacity: 1,
      customX: .04, customY: .5, thresholdDbfs: -12, alertBorderEnabled: true, alertBorderColor: '#ff2d2d',
      alertBorderOpacity: 1, alertBorderWidth: 3 },
    promotionKinds: { audio: false, motion: false, person: false },
  }])),
});

exports.largeSourceAudioWorkspace = (count = 1000) => ({
  mode: 'manual', localMonitorVolume: .18, audioMonitorEnabled: false,
  showAllAudioSources: true,
  sourceAudio: Object.fromEntries(Array.from({ length: count }, (_, index) =>
    [`other-scene-${index}`, { volume: .27, muted: false, monitor: false }])),
});
