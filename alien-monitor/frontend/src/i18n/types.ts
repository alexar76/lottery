export const LOCALES = ['en', 'ru', 'es'] as const;
export type Locale = (typeof LOCALES)[number];

export const LOCALE_LABELS: Record<Locale, string> = {
  en: 'EN',
  ru: 'RU',
  es: 'ES',
};

export type TranslationDict = Record<string, unknown>;
