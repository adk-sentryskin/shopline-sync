import { useTranslation } from "react-i18next";

export default function NotFound() {
  const { t } = useTranslation();

  return (
    <div>
      <h1>{t("404")}</h1>
    </div>
  );
}
