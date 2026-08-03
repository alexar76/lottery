/** Bearer token for protected monitor API routes (set at build via VITE_ALIEN_API_TOKEN). */
export function monitorApiToken(): string {
  return String(import.meta.env.VITE_ALIEN_API_TOKEN || '').trim();
}

export function monitorAuthHeaders(): Record<string, string> {
  const token = monitorApiToken();
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

export function monitorWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const basePath = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');
  const token = monitorApiToken();
  const qs = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${protocol}//${window.location.host}${basePath}/ws${qs}`;
}
