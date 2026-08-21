export type QuestionTheme = {
  id: string;
  mainClassName: string;
  appClassName: string;
  screenClassNames: Record<"welcome" | "question" | "concept" | "completion", string>;
};

export function getScreenTheme(screen: { kind: string; questionIndex?: number }): QuestionTheme;
