import type { AccountProfile } from './api';

export const avatarChoices: Array<{ id: AccountProfile['avatar']; icon: string; label: string }> = [
  { id: 'person', icon: '●', label: '人物' }, { id: 'camera', icon: '▣', label: '相机' },
  { id: 'shield', icon: '◆', label: '盾牌' }, { id: 'eye', icon: '◉', label: '眼睛' },
  { id: 'star', icon: '★', label: '星星' }, { id: 'sun', icon: '☀', label: '太阳' },
];
const roleLabels: Record<string, string> = { admin: '管理员', operator: '操作员', viewer: '观众',
  auditor: '审计员', exporter: '导出员' };
export const roleLabel = (role: string) => roleLabels[role] ?? role;
