const RESPONSE_SHEET_NAME = "Responses";
const SUMMARY_SHEET_NAME = "Summary";
const MAX_SUBMISSIONS_PER_IP_HOUR = 12;

const RESPONSE_HEADERS = [
  "received_at",
  "response_id",
  "survey_version",
  "client_token_hash",
  "meeting_paths",
  "compatibility_challenges",
  "compatibility_signals",
  "concept_usefulness",
  "concept_concerns",
  "must_get_right",
];

const QUESTION_RULES = {
  meeting_paths: {
    min: 1,
    max: 2,
    options: [
      "Friends or family",
      "College or work",
      "Shared interests",
      "Events or communities",
      "Social media",
      "Dating apps",
      "Mostly by chance",
      "I'm not sure",
    ],
  },
  compatibility_challenges: {
    min: 1,
    max: 2,
    options: [
      "Meeting the right people",
      "Understanding real intentions",
      "Knowing if values and personalities match",
      "Starting a meaningful conversation",
      "Trust and personal safety",
      "Social pressure or awkwardness",
      "Limited time or opportunities",
      "I don't think it is particularly difficult",
    ],
  },
  compatibility_signals: {
    min: 1,
    max: 3,
    options: [
      "Shared values",
      "Similar relationship intentions",
      "Personality",
      "Communication style",
      "Lifestyle",
      "Interests",
      "Family or cultural background",
      "Physical attraction",
    ],
  },
  concept_usefulness: {
    min: 1,
    max: 1,
    options: [
      "Extremely useful",
      "Quite useful",
      "Somewhat useful",
      "Not very useful",
      "Not useful",
      "I need more information",
    ],
  },
  concept_concerns: {
    min: 1,
    max: 2,
    options: [
      "Privacy and personal data",
      "AI understanding someone incorrectly",
      "Compatibility cannot be predicted",
      "Losing spontaneity or human judgement",
      "Fake profiles and safety",
      "Not enough relevant people",
      "The process taking too much effort",
      "Nothing concerns me yet",
    ],
  },
};

function doPost(event) {
  try {
    const payload = JSON.parse((event.postData && event.postData.contents) || "{}");
    const properties = PropertiesService.getScriptProperties();
    const expectedSecret = properties.getProperty("FEEDBACK_SHARED_SECRET");
    if (!expectedSecret || payload.internalSecret !== expectedSecret) {
      throw appError_("unauthorized");
    }

    const normalized = validateSubmission_(payload);
    if (normalized.website) return json_({ ok: true, discarded: true });

    const lock = LockService.getScriptLock();
    if (!lock.tryLock(5000)) throw appError_("temporarily_busy");
    try {
      enforceRateLimit_(payload.requestIp, expectedSecret);
      return json_(writeSubmission_(normalized, expectedSecret));
    } finally {
      lock.releaseLock();
    }
  } catch (error) {
    return json_({ ok: false, code: error && error.code ? error.code : "invalid_submission" });
  }
}

function validateSubmission_(payload) {
  const responseId = cleanToken_(payload.responseId, 36, "response_id");
  const surveyVersion = cleanToken_(payload.surveyVersion, 64, "survey_version");
  const clientToken = cleanToken_(payload.clientToken, 36, "client_token");
  const website = typeof payload.website === "string" ? payload.website.slice(0, 200) : "";
  const sourceAnswers = payload.answers;
  if (!sourceAnswers || typeof sourceAnswers !== "object" || Array.isArray(sourceAnswers)) {
    throw appError_("invalid_answers");
  }

  const answers = {};
  Object.keys(QUESTION_RULES).forEach(function (questionId) {
    const rule = QUESTION_RULES[questionId];
    const values = sourceAnswers[questionId];
    if (!Array.isArray(values) || values.length < rule.min || values.length > rule.max) {
      throw appError_("invalid_" + questionId);
    }
    const uniqueValues = Array.from(new Set(values));
    if (uniqueValues.length !== values.length || uniqueValues.some(function (value) {
      return typeof value !== "string" || rule.options.indexOf(value) === -1;
    })) {
      throw appError_("invalid_" + questionId);
    }
    answers[questionId] = uniqueValues;
  });

  const openAnswer = sourceAnswers.must_get_right || [];
  if (!Array.isArray(openAnswer) || openAnswer.length > 1) {
    throw appError_("invalid_must_get_right");
  }
  const mustGetRight = String(openAnswer[0] || "").trim();
  if (mustGetRight.length > 250) throw appError_("invalid_must_get_right");

  return {
    responseId: responseId,
    surveyVersion: surveyVersion,
    clientToken: clientToken,
    website: website,
    answers: answers,
    mustGetRight: mustGetRight,
  };
}

function writeSubmission_(submission, secret) {
  const spreadsheet = feedbackSpreadsheet_();
  const sheet = spreadsheet.getSheetByName(RESPONSE_SHEET_NAME);
  if (!sheet) throw appError_("sheet_not_configured");

  const clientHash = sha256_(submission.surveyVersion + ":" + submission.clientToken + ":" + secret);
  if (sheet.getLastRow() > 1) {
    const existing = sheet.getRange(2, 2, sheet.getLastRow() - 1, 3).getDisplayValues();
    const duplicate = existing.find(function (row) {
      return row[0] === submission.responseId || row[2] === clientHash;
    });
    if (duplicate) return { ok: true, duplicate: true };
  }

  // Prefix formula-leading user text so Sheets always stores it as data, never executable formula syntax.
  const safeOpenAnswer = sheetSafe_(submission.mustGetRight);
  sheet.appendRow([
    new Date(),
    submission.responseId,
    submission.surveyVersion,
    clientHash,
    submission.answers.meeting_paths.join(" | "),
    submission.answers.compatibility_challenges.join(" | "),
    submission.answers.compatibility_signals.join(" | "),
    submission.answers.concept_usefulness[0],
    submission.answers.concept_concerns.join(" | "),
    safeOpenAnswer,
  ]);
  return { ok: true, duplicate: false };
}

function enforceRateLimit_(requestIp, secret) {
  const source = String(requestIp || "unknown");
  const hourBucket = Utilities.formatDate(new Date(), "Etc/UTC", "yyyyMMddHH");
  const key = "feedback-rate:" + sha256_(source + ":" + hourBucket + ":" + secret);
  const cache = CacheService.getScriptCache();
  const count = Number(cache.get(key) || 0);
  if (count >= MAX_SUBMISSIONS_PER_IP_HOUR) throw appError_("rate_limited");
  cache.put(key, String(count + 1), 3600);
}

function setupFeedbackWorkbook() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  if (!spreadsheet) throw new Error("Run this function from a script bound to the feedback Sheet.");
  PropertiesService.getScriptProperties().setProperty("FEEDBACK_SPREADSHEET_ID", spreadsheet.getId());

  let responses = spreadsheet.getSheetByName(RESPONSE_SHEET_NAME);
  if (!responses) responses = spreadsheet.insertSheet(RESPONSE_SHEET_NAME);
  if (responses.getLastRow() === 0) {
    responses.getRange(1, 1, 1, RESPONSE_HEADERS.length).setValues([RESPONSE_HEADERS]);
  } else {
    // Never clear an existing response sheet. Refuse unexpected schemas so a
    // setup rerun cannot silently move columns or destroy collected research.
    const existingHeaders = responses.getRange(1, 1, 1, RESPONSE_HEADERS.length).getDisplayValues()[0];
    if (existingHeaders.join("|") !== RESPONSE_HEADERS.join("|")) {
      throw new Error("Responses sheet headers do not match this survey version.");
    }
  }
  responses.setFrozenRows(1);
  responses.getRange("A:A").setNumberFormat("yyyy-mm-dd hh:mm:ss");
  responses.autoResizeColumns(1, RESPONSE_HEADERS.length);

  let summary = spreadsheet.getSheetByName(SUMMARY_SHEET_NAME);
  if (!summary) summary = spreadsheet.insertSheet(SUMMARY_SHEET_NAME);
  summary.clear();
  summary.getCharts().forEach(function (chart) { summary.removeChart(chart); });
  summary.getRange("A1:B7").setValues([
    ["Metric", "Value"],
    ["Total responses", "=MAX(COUNTA(Responses!A:A)-1,0)"],
    ["Latest response", "=IFERROR(MAX(Responses!A2:A),\"\")"],
    ["Extremely or quite useful", "=COUNTIF(Responses!H:H,\"Extremely useful\")+COUNTIF(Responses!H:H,\"Quite useful\")"],
    ["Privacy concern", "=COUNTIF(Responses!I:I,\"*Privacy and personal data*\")"],
    ["AI accuracy concern", "=COUNTIF(Responses!I:I,\"*AI understanding someone incorrectly*\")"],
    ["Written suggestions", "=COUNTIF(Responses!J:J,\"<>\")-1"],
  ]);
  summary.getRange("D1:E7").setValues([
    ["Usefulness", "Responses"],
    ["Extremely useful", "=COUNTIF(Responses!H:H,D2)"],
    ["Quite useful", "=COUNTIF(Responses!H:H,D3)"],
    ["Somewhat useful", "=COUNTIF(Responses!H:H,D4)"],
    ["Not very useful", "=COUNTIF(Responses!H:H,D5)"],
    ["Not useful", "=COUNTIF(Responses!H:H,D6)"],
    ["Need more information", "=COUNTIF(Responses!H:H,\"I need more information\")"],
  ]);
  summary.setFrozenRows(1);
  summary.autoResizeColumns(1, 5);
  const chart = summary.newChart()
    .asBarChart()
    .addRange(summary.getRange("D1:E7"))
    .setPosition(9, 1, 0, 0)
    .setOption("title", "Omiryn concept usefulness")
    .setOption("legend", { position: "none" })
    .build();
  summary.insertChart(chart);
}

function feedbackSpreadsheet_() {
  const id = PropertiesService.getScriptProperties().getProperty("FEEDBACK_SPREADSHEET_ID");
  if (!id) throw appError_("sheet_not_configured");
  return SpreadsheetApp.openById(id);
}

function cleanToken_(value, maxLength, code) {
  const token = String(value || "");
  if (!token || token.length > maxLength || !/^[A-Za-z0-9_.-]+$/.test(token)) {
    throw appError_("invalid_" + code);
  }
  return token;
}

function sheetSafe_(value) {
  return /^[=+\-@]/.test(value) ? "'" + value : value;
}

function sha256_(value) {
  const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, value, Utilities.Charset.UTF_8);
  return digest.map(function (byte) {
    const normalized = byte < 0 ? byte + 256 : byte;
    return ("0" + normalized.toString(16)).slice(-2);
  }).join("");
}

function appError_(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

function json_(body) {
  // ContentService redirects every response through a temporary
  // script.googleusercontent.com URL. Some server-side clients can lose that
  // acknowledgement even after the Sheet write succeeds, so return the same
  // JSON text directly through HtmlService and let the Worker parse the body.
  return HtmlService.createHtmlOutput(JSON.stringify(body));
}
