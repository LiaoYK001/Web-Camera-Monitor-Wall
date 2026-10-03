export default function MonitorPreferenceStatus({ loaded, error, retry }: {
  loaded: boolean; error: string; retry: () => void;
}) {
  if (loaded && !error) return null;
  return <div className="monitor-preference-status" role={error ? 'alert' : 'status'}>
    <span>{error || '正在读取监控偏好…'}{!loaded && ' 读取成功后恢复账号设置，偏好控制暂不可用。'}</span>
    {error && <button type="button" onClick={retry}>重试账号偏好</button>}
  </div>;
}
