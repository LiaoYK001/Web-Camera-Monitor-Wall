import { exportActive, exportError, type useNvrExportJobs } from './useNvrExportJobs';
import { useSecurityUpdateRecovery } from './pwaContinuity';

const labels = { queued: '等待处理', running: '正在导出', cancelling: '正在取消', completed: '导出完成',
  failed: '导出失败', cancelled: '已取消', interrupted: '重启中断' };
const utc = (value: number) => new Date(value).toISOString().replace('T', ' ').replace('.000Z', ' UTC');

export function NvrExportPanel({ exports }: { exports: ReturnType<typeof useNvrExportJobs> }) {
  // A forced security replacement can strand a submission whose response was lost.
  // Re-posting the same request id would duplicate an accepted export, so after an
  // update the panel reconciles read-only from the job list. A genuinely failed job
  // keeps its normal "重新导出" control, which is not an unknown-outcome retry.
  const recovery = useSecurityUpdateRecovery();
  return <section className="nvr-export-panel" aria-label="导出任务">
    <header><h2>证据导出任务</h2><button type="button" disabled={exports.busy || !exports.ready} onClick={() => void exports.refresh()}>刷新任务</button></header>
    <p>离开页面后任务继续执行，重新打开可查看结果。导出成功后自动锁定源片段；快速导出的断档会列入证据清单。</p>
    {exports.error && <div role="alert">{exports.error}</div>}
    {exports.pending && (recovery.state !== 'none'
      ? <div role="status">上一提交结果尚待确认。安全更新后不会用同一请求标识重复提交；该任务是否已受理，请以任务列表中的实际状态为准。
        <button type="button" disabled={exports.busy || !exports.ready} onClick={() => void exports.refresh()}>刷新任务列表</button></div>
      : <div role="status">上一提交结果尚待确认。恢复提交会复用原请求标识，避免重复导出。
        <button type="button" disabled={exports.busy || !exports.ready} onClick={exports.recover}>恢复同一次提交</button></div>)}
    {!exports.jobs.length && <p>{!exports.allowed ? '此账号暂不可查看或创建导出任务。' : exports.ready ? '暂无导出任务。选择摄像机与时间范围后创建。' : '正在读取当前账号的任务…'}</p>}
    {exports.jobs.map(job => <article key={job.id} className="nvr-export-job" data-state={job.state}>
      <header><strong>{labels[job.state]} · {job.request.mode === 'exact' ? '精确' : '快速'}</strong>
        {exportActive(job) && <button type="button" disabled={exports.busy || job.state === 'cancelling'} onClick={() => exports.cancel(job.id)}>取消导出</button>}
        {['failed', 'interrupted', 'cancelled'].includes(job.state) && <button type="button" disabled={exports.busy || !!exports.pending} onClick={() => exports.submit(job.request)}>重新导出</button>}
      </header>
      <p>{job.request.cameraIds.join('、')} · 请求 {utc(job.request.fromUtcMs)} — {utc(job.request.toUtcMs)}</p>
      {job.error && <p role="status">{exportError(job.error)}</p>}
      {job.result && <div className="export-result">
        <strong>实际边界 {utc(job.result.effectiveRange.fromUtcMs)} — {utc(job.result.effectiveRange.toUtcMs)}</strong>
        <span>清单 SHA-256 {job.result.manifestSha256}</span>
        <a href={job.result.manifestUrl} download>下载证据清单</a>
        {job.result.files.map(file => <div key={file.name}>
          <a href={file.downloadUrl} download>{file.cameraId} · 下载视频</a>
          <span> SHA-256 {file.sha256}</span>
          {!!(file.coverage?.gapCount ?? file.coverage?.gaps.length) && <strong> 含 {file.coverage?.gapCount ?? file.coverage?.gaps.length} 处录像断档；视频只包含现有片段，时间不连续。</strong>}
          {file.coverage?.overlap && <strong> 存在重叠片段，详见清单。</strong>}
        </div>)}
      </div>}
    </article>)}
  </section>;
}
