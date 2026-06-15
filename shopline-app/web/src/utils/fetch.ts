export const fetchFn = (
  url: RequestInfo | URL,
  options?: RequestInit,
  fn = window.fetch
) => {
  const headers = new Headers(options && options.headers);
  headers.append("X-Requested-With", "XMLHttpRequest");
  return fn(url, { ...options, headers });
};

export const useAuthFetch = () => {
  return async (...args: Parameters<typeof fetchFn>) => {
    const response = await fetchFn(...args);
    return response;
  };
};
