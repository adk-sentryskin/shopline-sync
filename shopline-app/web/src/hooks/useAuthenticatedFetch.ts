import { useAppBridge } from "./useAppBridge";
import { shared, Redirect } from '@shoplinedev/appbridge'
const search = new URLSearchParams(location.search);

export function useAuthenticatedFetch() {
  const app = useAppBridge();
  const isEmbedded = !!search.get("lang") 
  
  return async (uri: string, options?: Record<string, any> ) => {
    let token
    if (isEmbedded) {
      token = await shared.getSessionToken(app);
    }
    const { headers, ...restOptions } = options || {}
    const response = await fetch(uri, {
      headers: {
        ...headers,
        'X-Requested-With': 'XMLHttpRequest',
        'Authorization':  token ? `Bearer ${token}` : undefined,
      },
      ...restOptions
    });
    checkHeadersForReauthorization(response.headers, app);
    return response;
  };
}

const checkHeadersForReauthorization = (headers: Headers, app: any) => {
  if (headers.get("X-SHOPLINE-API-Request-Failure-Reauthorize") === "1") {
    const authUrlHeader =
      headers.get("X-SHOPLINE-API-Request-Failure-Reauthorize-Url") ||
      `/api/auth`;

    const redirect = Redirect.create(app);
    redirect.replaceTo(authUrlHeader.startsWith("/")
    ? `https://${window.location.host}${authUrlHeader}`
    : authUrlHeader)
  }
}
