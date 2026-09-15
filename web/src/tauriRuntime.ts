import { invoke } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { NativeTranslationApi } from './nativeApi';

/** 仅由已验证 Tauri 宿主的宠物入口加载。 */
export const nativeApi = new NativeTranslationApi((command, args) => invoke(command, args));

export interface PetWindowControls {
  startDragging(): Promise<void>;
  hide(): Promise<void>;
}

export const petWindowControls: PetWindowControls = {
  startDragging: () => getCurrentWindow().startDragging(),
  hide: () => getCurrentWindow().hide(),
};
