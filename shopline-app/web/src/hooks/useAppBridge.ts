import Client,{shared} from "@shoplinedev/appbridge";

const search = new URLSearchParams(location.search);
const app = Client.createApp({
  appKey: search.get("appkey") || import.meta.env.VITE_APP_KEY,
  host: shared.getHost()
});

export const useAppBridge = () => {
  return app;
};
