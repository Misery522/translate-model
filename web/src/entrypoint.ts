/** URL 只能选择已处于 Tauri 内的视图，不能让普通网页获得原生能力。 */
export function selectClient(native: boolean, search: string): 'web' | 'pet' | 'blocked' {
  if (!native) return 'web';
  return new URLSearchParams(search).get('view') === 'pet' ? 'pet' : 'blocked';
}
