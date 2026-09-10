// IndexedDB keeps the analyzed photo with its layout, including uploads too large
// for sessionStorage. A per-tab key prevents another tab overwriting this design.
export async function yardState(value) {
  const db = await new Promise((resolve, reject) => {
    const request = indexedDB.open('yard-agent', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('designs');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  try {
    let key = sessionStorage.getItem('yard-design-id');
    if (!key && value !== undefined) {
      key = [...crypto.getRandomValues(new Uint8Array(16))].map(n => n.toString(16).padStart(2, '0')).join('');
      sessionStorage.setItem('yard-design-id', key);
    }
    if (!key) return null;
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction('designs', value === undefined ? 'readonly' : 'readwrite');
      const store = transaction.objectStore('designs');
      const request = value === undefined ? store.get(key) : store.put(value, key);
      transaction.oncomplete = () => resolve(value === undefined ? request.result : value);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error || new Error('Storage unavailable'));
    });
  } finally { db.close(); }
}
