export const NON_ENGLISH_REPORT_NOTICE =
  "Report text was returned in a non-English language. Re-run the report with the English-only research setting to regenerate this section.";

const CJK_PATTERN = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;

export function containsCjkText(value: string): boolean {
  return CJK_PATTERN.test(value);
}

export function englishOrNotice(value: string): string {
  return containsCjkText(value) ? NON_ENGLISH_REPORT_NOTICE : value;
}
