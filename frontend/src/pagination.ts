/** Zero-based page bounds. Only the returned window is rendered. */
export function pageWindow(total: number, pageSize: number, requestedPage: number) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.max(0, Math.min(Math.floor(requestedPage), pageCount - 1));
  const start = page * pageSize;
  return { page, pageCount, start, end: Math.min(start + pageSize, total) };
}

export function pageForIndex(index: number, pageSize: number) {
  return Math.floor(Math.max(0, index) / pageSize);
}
