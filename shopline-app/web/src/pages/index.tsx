import { useAppBridge } from "../hooks/useAppBridge";
import { Redirect, Message } from "@shoplinedev/appbridge";
import { useAuthenticatedFetch } from "../hooks/useAuthenticatedFetch";
import styles from "./index.module.css";
import { useTranslation } from "react-i18next";

export default () => {
  const fetch = useAuthenticatedFetch();
  const app = useAppBridge();
  const { t } = useTranslation();

  const gotoHome = () => {
    const redirect = Redirect.create(app);
    redirect.routerTo("/");
  };

  const handleCreateProduct = async () => {
    const response = await fetch("/api/products/create");

    if (response.ok) {
      Message.create(app).open({
        messageInfo: t("message.success"),
        type: "success",
      });
    } else {
      Message.create(app).open({
        messageInfo: t("message.failure"),
        type: "error",
      });
    }
  };

  return (
    <div>
      <div className={styles.title}>{t("welcome")}</div>
      <div>
        <p>
          {t("action.tip")}
          <button onClick={gotoHome}>{t("action.home")}</button>
          <button onClick={handleCreateProduct}>{t("action.product")}</button>
        </p>
      </div>
    </div>
  );
};
