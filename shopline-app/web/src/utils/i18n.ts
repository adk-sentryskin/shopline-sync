import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import resourcesToBackend from "i18next-resources-to-backend";
import { match } from "@formatjs/intl-localematcher";

const DEFAULT_APP_LOCALE = "en";

const locales = import.meta.glob("../locales/*.json", {
  eager: false,
  import: "default",
});

/**
 * @see https://developer.shopline.com/docsv2/ec20
 * @returns en | zh-hans-cn
 */
const SUPPORTED_APP_LOCALES = Object.keys(locales).map((locale) => {
  const match = locale.match(/locales\/(.*).json/);
  return match ? match[1] : "";
});

let _userLocale: string;

export function getQueryLang() {
  if (_userLocale) {
    return _userLocale;
  }
  const query = new URLSearchParams(window.location.search);
  const locale = query.get("lang") || DEFAULT_APP_LOCALE;
  _userLocale = match([locale], SUPPORTED_APP_LOCALES, DEFAULT_APP_LOCALE);
  return _userLocale;
}

/**
 * i18next initialization
 * @see https://www.i18next.com
 */
export async function initI18next() {
  return await i18next
    .use(initReactI18next)
    .use(
      resourcesToBackend((locale: string) => {
        return locales[`../locales/${locale}.json`]();
      })
    )
    .init({
      debug: import.meta.env.DEV,
      lng: getQueryLang(),
      fallbackLng: DEFAULT_APP_LOCALE,
      supportedLngs: SUPPORTED_APP_LOCALES,
      interpolation: {
        escapeValue: false,
      },
      lowerCaseLng: true,
      react: {
        useSuspense: false,
      },
    });
}
