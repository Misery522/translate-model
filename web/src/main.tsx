import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    // 新版 worker 等现有页面结束后再接管，不中断正在进行的翻译。
    void navigator.serviceWorker.register('/sw.js', { type: 'module', scope: '/' }).catch(() => {
      // 离线壳是增强能力；注册失败不会阻断在线翻译。
    });
  });
}
