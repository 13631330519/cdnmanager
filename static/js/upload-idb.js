(function (global) {
    const DB_NAME = 'cdnmanager-upload';
    const DB_VERSION = 1;

    function openDb() {
        return new Promise((resolve, reject) => {
            const req = indexedDB.open(DB_NAME, DB_VERSION);
            req.onupgradeneeded = () => {
                const db = req.result;
                if (!db.objectStoreNames.contains('sessions')) {
                    db.createObjectStore('sessions', { keyPath: 'jobId' });
                }
                if (!db.objectStoreNames.contains('fileStates')) {
                    const store = db.createObjectStore('fileStates', { keyPath: 'key' });
                    store.createIndex('jobId', 'jobId', { unique: false });
                }
            };
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    }

    async function withStore(storeName, mode, fn) {
        const db = await openDb();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(storeName, mode);
            const store = tx.objectStore(storeName);
            const result = fn(store);
            tx.oncomplete = () => resolve(result);
            tx.onerror = () => reject(tx.error);
        });
    }

    const UploadIdb = {
        async saveSession(session) {
            await withStore('sessions', 'readwrite', (store) => {
                store.put(session);
            });
        },

        async getSession(jobId) {
            return withStore('sessions', 'readonly', (store) => {
                return new Promise((resolve, reject) => {
                    const req = store.get(jobId);
                    req.onsuccess = () => resolve(req.result || null);
                    req.onerror = () => reject(req.error);
                });
            });
        },

        async getActiveSession() {
            return withStore('sessions', 'readonly', (store) => {
                return new Promise((resolve, reject) => {
                    const req = store.openCursor(null, 'prev');
                    req.onsuccess = () => {
                        const cursor = req.result;
                        if (!cursor) return resolve(null);
                        const val = cursor.value;
                        if (val && val.active) resolve(val);
                        else resolve(null);
                    };
                    req.onerror = () => reject(req.error);
                });
            });
        },

        async clearSession(jobId) {
            await withStore('sessions', 'readwrite', (store) => store.delete(jobId));
            const db = await openDb();
            await new Promise((resolve, reject) => {
                const tx = db.transaction('fileStates', 'readwrite');
                const store = tx.objectStore('fileStates');
                const index = store.index('jobId');
                const req = index.openCursor(IDBKeyRange.only(jobId));
                req.onsuccess = () => {
                    const cursor = req.result;
                    if (cursor) {
                        cursor.delete();
                        cursor.continue();
                    }
                };
                tx.oncomplete = () => resolve();
                tx.onerror = () => reject(tx.error);
            });
        },

        async saveFileState(jobId, fileId, path, patch) {
            const key = `${jobId}:${fileId || path}`;
            const existing = await withStore('fileStates', 'readonly', (store) => {
                return new Promise((resolve, reject) => {
                    const req = store.get(key);
                    req.onsuccess = () => resolve(req.result || {});
                    req.onerror = () => reject(req.error);
                });
            });
            const next = Object.assign({}, existing, patch, { key, jobId, fileId, path });
            await withStore('fileStates', 'readwrite', (store) => store.put(next));
        },

        async listFileStates(jobId) {
            return withStore('fileStates', 'readonly', (store) => {
                return new Promise((resolve, reject) => {
                    const index = store.index('jobId');
                    const req = index.getAll(IDBKeyRange.only(jobId));
                    req.onsuccess = () => resolve(req.result || []);
                    req.onerror = () => reject(req.error);
                });
            });
        },
    };

    global.UploadIdb = UploadIdb;
})(window);
