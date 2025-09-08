export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path)
  return res.json()
}
