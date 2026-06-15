import { Redirect } from "@shoplinedev/appbridge";
import { useEffect } from "react";
import { useAppBridge } from "../hooks/useAppBridge";

export default function ExitIframe() {
  const app = useAppBridge();

  useEffect(() => {
    const redirect = Redirect.create(app);
    const search = new URL(location.href).searchParams;
    redirect.replaceTo(search.get("redirectUri") as string);
  }, []);
  return <></>
}
