interface StreamStore {
  screen: MediaStream | null;
  camera: MediaStream | null;
  audio: MediaStream | null;
}

const store: StreamStore = { screen: null, camera: null, audio: null };

export function storeMonitoringStreams(s: Partial<StreamStore>): void {
  if (s.screen !== undefined) store.screen = s.screen;
  if (s.camera !== undefined) store.camera = s.camera;
  if (s.audio !== undefined) store.audio = s.audio;
}

function take(key: keyof StreamStore): MediaStream | null {
  const s = store[key];
  store[key] = null;
  return s;
}

export const takeScreenStream = () => take("screen");
export const takeCameraStream = () => take("camera");
export const takeAudioStream = () => take("audio");

export function clearMonitoringStreams(): void {
  for (const key of ["screen", "camera", "audio"] as const) {
    store[key]?.getTracks().forEach((t) => t.stop());
    store[key] = null;
  }
}
