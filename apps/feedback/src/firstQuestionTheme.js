export function getQuestionScreenClass(questionIndex) {
  return questionIndex === 0
    ? "question-screen question-screen--playground"
    : "question-screen";
}
