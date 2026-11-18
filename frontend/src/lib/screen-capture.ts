// Module-level singleton — holds the screen MediaStream between lobby and session pages.
// The stream is acquired in the lobby (user gesture), kept alive through navigation,
// and consumed by the interview recorder in the session page.

let _stream: MediaStream | null = null;

export function storeScreenStream(s: MediaStream): void {
  _stream = s;
}

export function getScreenStream(): MediaStream | null {
  return _stream;
}

export function clearScreenStream(): void {
  _stream?.getTracks().forEach((t) => t.stop());
  _stream = null;
}
