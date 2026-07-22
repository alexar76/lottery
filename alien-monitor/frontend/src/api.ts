/** API paths respecting Vite base (e.g. /monitor/ on production). */
export function apiUrl(path: string): string {
  const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, '') || '';
  const p = path.startsWith('/') ? path : `/${path}`;
  return `${base}${p}`;
}
