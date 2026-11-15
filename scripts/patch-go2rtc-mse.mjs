// Adapt the generated player only; keep the pinned upstream checkout intact.
export function retainGo2rtcMseHistory(source) {
  const replacements = [
    ['const start = end - 5;', `// Removing inside a GOP also removes dependencies up to the next keyframe.
                    // Keep history separate from the five-second live-edge recovery limit.
                    const start = end - 30;
                    const liveStart = end - 5;`],
    ['if (this.video.currentTime < start) {', 'if (this.video.currentTime < liveStart) {'],
    ['this.video.currentTime = start;', 'this.video.currentTime = liveStart;'],
  ];
  for (const [before, after] of replacements) {
    if (source.split(before).length !== 2) throw new Error('Unexpected upstream MSE history handler');
    source = source.replace(before, after);
  }
  return source;
}
