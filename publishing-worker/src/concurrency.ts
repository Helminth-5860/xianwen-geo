type Waiter = {
  resolve: () => void;
  reject: (error: Error) => void;
};

function boundedInt(name: string, fallback: number, min: number, max: number) {
  const raw = Number.parseInt(process.env[name] || "", 10);
  const value = Number.isFinite(raw) ? raw : fallback;
  return Math.max(min, Math.min(max, value));
}

const maxConcurrency = boundedInt("PUBLISHING_WORKER_MAX_CONCURRENCY", 1, 1, 4);
const maxQueue = boundedInt("PUBLISHING_WORKER_MAX_QUEUE", 20, 1, 200);
let active = 0;
const waiters: Waiter[] = [];

async function acquire() {
  if (active < maxConcurrency) {
    active += 1;
    return;
  }
  if (waiters.length >= maxQueue) throw new Error("worker_busy");
  await new Promise<void>((resolve, reject) => waiters.push({ resolve, reject }));
  active += 1;
}

function release() {
  active = Math.max(0, active - 1);
  const next = waiters.shift();
  if (next) next.resolve();
}

export async function withPublishPermit<T>(work: () => Promise<T>): Promise<T> {
  await acquire();
  try {
    return await work();
  } finally {
    release();
  }
}

export function publishConcurrencyState() {
  return {
    active,
    queued: waiters.length,
    maxConcurrency,
    maxQueue,
  };
}
