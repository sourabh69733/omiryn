const playgroundV1 = {
  id: "playground-v1",
  mainClassName: "feedback-main--playground-v1",
  appClassName: "feedback-app--playground-v1",
  screenClassNames: {
    welcome: "welcome-screen--playground-v1",
    question: "question-screen--playground-v1",
    concept: "concept-screen--playground-v1",
    completion: "completion-screen--playground-v1",
  },
};

export function getScreenTheme(_screen) {
  return playgroundV1;
}
