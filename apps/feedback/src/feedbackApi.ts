export type SubmissionMode = "preview" | "submitted";

export type FeedbackSubmission = {
  responseId: string;
  surveyVersion: string;
  clientToken: string;
  answers: Record<string, string[]>;
  website: string;
};

type SubmissionResponse = {
  ok?: boolean;
  code?: string;
};

const clientTokenStorageKey = "omiryn-feedback-client-token-v1";

export function getOrCreateClientToken(): string {
  const existing = window.localStorage.getItem(clientTokenStorageKey);
  if (existing) return existing;
  const token = crypto.randomUUID();
  window.localStorage.setItem(clientTokenStorageKey, token);
  return token;
}

export async function submitFeedback(payload: FeedbackSubmission): Promise<SubmissionMode> {
  const configuredEndpoint = import.meta.env.VITE_FEEDBACK_SUBMISSION_URL?.trim();

  // Local UI work stays self-contained until the Apps Script URL and Worker secrets exist.
  if (import.meta.env.DEV && !configuredEndpoint) {
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    window.sessionStorage.setItem("omiryn-feedback-last-preview", JSON.stringify(payload));
    return "preview";
  }

  const response = await fetch(configuredEndpoint || "/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  let result: SubmissionResponse = {};
  try {
    result = (await response.json()) as SubmissionResponse;
  } catch {
    // A non-JSON response is treated as an unconfirmed submission, even if it returned 2xx.
  }

  if (!response.ok || result.ok !== true) {
    throw new Error(result.code || "submission_failed");
  }
  return "submitted";
}
