// The API key lives in this browser only (localStorage), never in the code or the build.
const STORAGE_KEY = 'codeevidence.apiKey'

export function getApiKey(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    return '' // storage blocked (private mode): the user is asked again
  }
}

export function setApiKey(key: string): void {
  try {
    if (key) localStorage.setItem(STORAGE_KEY, key)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // nothing to do: the key just will not be remembered
  }
}
