/// <reference types="vite/client" />

import "i18next";

declare module "i18next" {
  /**
   * support i18next.t("key")
   * @override
   * @see https://www.i18next.com/overview/typescript
   */
  interface CustomTypeOptions {
    defaultNS: "en";
    resources: {
      en: typeof import("./locales/en.json");
    };
  }
}
