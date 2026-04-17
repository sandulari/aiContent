// Auth tokens are now stored in httpOnly cookies — JavaScript cannot
// (and should not) read them.  These functions are kept as no-ops for
// any call-sites that haven't been cleaned up yet.

export function getToken(): string | null {
  return null;
}

export function setToken(_token: string): void {}

export function removeToken(): void {}

export function isAuthenticated(): boolean {
  // We can't read httpOnly cookies from JS (that's the point).
  // Shell will verify authentication on mount via /api/auth/me.
  return true;
}
