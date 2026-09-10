import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { isTauri } from '@tauri-apps/api/core';
import App from './App';
import { selectClient } from './entrypoint';
import './styles.css';

const root = createRoot(document.getElementById('root')!);
const client = selectClient(isTauri(), window.location.search);
if (client === 'pet') {
  void import('./PetApp')
    .then(({ default: PetApp }) => {
      root.render(
        <StrictMode>
          <PetApp />
        </StrictMode>,
      );
    })
    .catch(() => {
      root.render(<p role="alert">小译界面加载失败，请重新打开应用或检查安装完整性。</p>);
    });
} else if (client === 'web') {
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
} else {
  root.render(<p role="alert">桌面入口无效，请从译境托盘重新打开。</p>);
}

if (client === 'web' && import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    // 新版 worker 等现有页面结束后再接管，不中断正在进行的翻译。
    void navigator.serviceWorker.register('/sw.js', { type: 'module', scope: '/' }).catch(() => {
      // 离线壳是增强能力；注册失败不会阻断在线翻译。
    });
  });
}
