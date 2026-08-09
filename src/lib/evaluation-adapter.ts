import type { EvaluationResponse } from "../api/evaluations";
import type { StreamEvaluationOutput } from "./evaluation-types";

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function number(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function boolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function strings(value: unknown): string[] {
  return array(value).filter((item): item is string => typeof item === "string");
}

function titleCase(value: string): string {
  return value
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function resultIsBlocking(result: string): boolean {
  return ["fail", "unresolved", "clarification_required", "exception_review", "not_implemented"].includes(result);
}

function ruleCorrection(result: string, field: string): string | undefined {
  if (result === "unresolved") return `Provide a clear value and supporting evidence for ${titleCase(field)}.`;
  if (result === "clarification_required") return `Clarify ${titleCase(field)} and remove contradictory or incomplete statements.`;
  if (result === "exception_review") return `Attach the required justification and approval for ${titleCase(field)}.`;
  if (result === "not_implemented") return "This check requires manual scrutiny because no automated verifier is configured.";
  if (result === "fail") return `Correct the non-compliance related to ${titleCase(field)} before resubmission.`;
  return undefined;
}

export function adaptEvaluation(response: EvaluationResponse): StreamEvaluationOutput {
  const scoring = record(response.scoring);
  const rules = record(response.rule_evaluation);
  const summary = record(rules.summary);
  const document = record(response.document_audit);
  const gate = record(response.document_gate ?? scoring.document_gate);
  const priorProject = record(response.prior_project_check);
  const quality = record(scoring.document_quality);
  const validation = record(scoring.validation);

  const detailedScores: StreamEvaluationOutput["detailedScores"] = [];
  const categoryScores: StreamEvaluationOutput["categoryScores"] = [];

  for (const rawCategory of array(scoring.category_scores)) {
    const category = record(rawCategory);
    const categoryName = text(category.category, "Uncategorised");
    const categoryReleased = boolean(category.released, false);
    categoryScores.push({
      name: categoryName,
      awarded: categoryReleased ? nullableNumber(category.awarded) : null,
      maximum: number(category.maximum),
      released: categoryReleased,
    });

    for (const rawCriterion of array(category.criteria)) {
      const criterion = record(rawCriterion);
      const evidence = array(criterion.evidence).map((rawEvidence) => {
        const item = record(rawEvidence);
        const page = nullableNumber(item.source_page);
        const excerpt = text(item.text, text(item.keyword, "Evidence matched"));
        return {
          text: page && page > 0 ? `Page ${page}: ${excerpt}` : excerpt,
          sourcePage: page,
          sourceSection: text(item.source_section) || null,
          documentRole: text(item.document_role) || null,
          verificationStatus: text(item.verification_status) || null,
        };
      });
      const awarded = nullableNumber(criterion.awarded_score);
      detailedScores.push({
        key: text(criterion.criterion_id, crypto.randomUUID()),
        criterion: text(criterion.label, text(criterion.criterion_id, "Criterion")),
        category: categoryName,
        maximum: number(criterion.maximum_score),
        awarded,
        ordinalGrade: nullableNumber(criterion.ordinal_grade),
        criterionStatus: text(criterion.criterion_status, awarded === null ? "unresolved" : "partially_supported"),
        released: boolean(criterion.released, awarded !== null && evidence.length > 0),
        evidenceCount: number(criterion.evidence_count, evidence.length),
        missingEvidence: strings(criterion.missing_evidence),
        evidence,
      });
    }
  }

  const hardRules: StreamEvaluationOutput["hardScreening"]["rules"] = array(rules.results).map((rawRule) => {
    const rule = record(rawRule);
    const result = text(rule.result, "unresolved");
    const field = text(rule.field, "required information");
    return {
      id: text(rule.rule_id, field),
      passed: !resultIsBlocking(result),
      label: titleCase(field),
      reason: text(rule.detail, titleCase(result)),
      correction: ruleCorrection(result, field),
    };
  });

  const failedReasons = hardRules.filter((rule) => !rule.passed).map((rule) => rule.reason);
  const totalScore = nullableNumber(scoring.total_score);
  const diagnosticScore = nullableNumber(scoring.diagnostic_score);
  const maximumScore = Math.max(1, number(scoring.maximum_score, 100));
  const scorePercent = totalScore === null ? null : (totalScore / maximumScore) * 100;
  const automaticProgression = boolean(summary.automatic_progression);
  const hasHardFailure = array(rules.results).some((rawRule) => {
    const rule = record(rawRule);
    return text(rule.result) === "fail" && text(rule.severity, "error") === "error";
  });
  const abstention = boolean(scoring.abstention, totalScore === null);
  const advisoryOnly = boolean(scoring.advisory_only, true);
  const modelReliability = number(scoring.confidence);
  const abstentionReasons = strings(scoring.abstention_reasons);
  const evaluationFailed = response.status === "error";
  const gateStatus = text(
    gate.status,
    evaluationFailed ? "evaluation_failed" : "legacy_unverified",
  );
  const gateAccepted = boolean(gate.accepted, gateStatus === "accepted");
  const gateReasons = strings(gate.reasons);
  if (evaluationFailed && gateReasons.length === 0) {
    gateReasons.push(
      text(
        response.error_message,
        "Evaluation failed before document-gate results were persisted.",
      ),
    );
  }
  const scoringStatus = text(
    scoring.scoring_status,
    evaluationFailed ? "failed" : totalScore === null ? "abstained" : "released",
  );
  const notScored = !gateAccepted || abstention || totalScore === null || scoringStatus !== "released";

  const status: StreamEvaluationOutput["status"] = notScored
    ? "not_scored"
    : hasHardFailure
      ? "rejected"
      : (!automaticProgression || (scorePercent ?? 0) < 80 ? "revision" : "approved");

  const releasedScores = detailedScores.filter((item) => item.released && item.awarded !== null);
  const strengths = releasedScores
    .filter((item) => item.maximum > 0 && (item.awarded ?? 0) / item.maximum >= 0.65)
    .sort((a, b) => ((b.awarded ?? 0) / b.maximum) - ((a.awarded ?? 0) / a.maximum))
    .slice(0, 6)
    .map((item) => `${item.criterion}: ${item.awarded}/${item.maximum}`);

  const weaknesses = releasedScores
    .filter((item) => item.maximum > 0 && (item.awarded ?? 0) / item.maximum < 0.35)
    .sort((a, b) => ((a.awarded ?? 0) / a.maximum) - ((b.awarded ?? 0) / b.maximum))
    .slice(0, 8)
    .map((item) => `${item.criterion}: weak verified support (${item.awarded}/${item.maximum}).`);

  const unresolved = detailedScores
    .filter((item) => !item.released)
    .slice(0, 8)
    .map((item) => `${item.criterion}: ${item.missingEvidence[0] ?? "No contract-accepted evidence was found."}`);

  const riskAreas = [
    ...gateReasons,
    ...hardRules.filter((rule) => !rule.passed).map((rule) => `${rule.label}: ${rule.reason}`),
  ].filter((item, index, values) => item && values.indexOf(item) === index).slice(0, 10);

  const improvementSuggestions = [
    ...hardRules.map((rule) => rule.correction).filter((item): item is string => Boolean(item)),
    ...unresolved.map((item) => `Provide verified evidence for ${item}`),
    ...weaknesses.map((item) => `Strengthen ${item}`),
  ].filter((item, index, values) => values.indexOf(item) === index).slice(0, 12);

  const wordCount = number(document.word_count, number(quality.word_count));
  const pageCount = number(document.page_count, 0) || null;
  const overallCoverage = number(scoring.information_sufficiency, number(scoring.evidence_coverage));
  const ocrPages = array(document.ocr_pages).filter((item): item is number => typeof item === "number");
  const gateReasonText = gateReasons.join(" ");

  const finalRecommendation = !gateAccepted
    ? `Not scored — ${gateReasonText || titleCase(gateStatus)}`
    : notScored
      ? `Not scored — ${abstentionReasons[0] ?? "verified evidence is insufficient for a reliable advisory score"}`
      : hasHardFailure
        ? "Hard-screening failure — correction is required before expert scoring"
        : (scorePercent ?? 0) >= 80
          ? "Highly competitive preliminary band — proceed to expert committee scrutiny"
          : (scorePercent ?? 0) >= 60
            ? "Conditional preliminary band — expert review and targeted revision required"
            : "Below the 60-point preliminary cut-off — expert review and substantial revision required";

  return {
    schemaVersion: "4.0",
    engine: text(response.engine_version, text(scoring.model_source, "document-gate-v1")),
    status,
    scoringStatus,
    totalScore,
    diagnosticScore,
    documentGate: {
      status: gateStatus,
      accepted: gateAccepted,
      scoringAllowed: boolean(gate.scoring_allowed, gateAccepted),
      documentType: text(gate.document_type, "unknown"),
      declaredRole: text(gate.declared_role, text(document.document_role, "main_proposal")),
      classifiedRole: text(gate.classified_role, "unknown"),
      roleStatus: text(
        gate.role_status,
        evaluationFailed ? "uncertain" : "legacy_unverified",
      ),
      structureCoverage: number(gate.structure_coverage),
      schemeRelevance: number(gate.scheme_relevance),
      reasons: gateReasons,
    },
    hardScreening: {
      result: failedReasons.length ? "fail" : "pass",
      failedReasons,
      rules: hardRules,
    },
    researchStream: {
      id: "coal-energy",
      name: "Coal R&D Proposal Evaluation",
      modelProfile: [
        text(scoring.model_source, "document-gate-v1"),
        text(scoring.model_version) ? `v${text(scoring.model_version)}` : "",
        number(scoring.training_rows) > 0 ? `${number(scoring.training_rows).toLocaleString()} weak-supervision training records` : "",
        modelReliability > 0 ? `${Math.round(modelReliability * 100)}% uncalibrated reliability indicator` : "",
        advisoryOnly ? "advisory human-in-the-loop" : "",
      ].filter(Boolean).join(" · "),
    },
    documentAudit: {
      source: text(document.file_type, "server extraction"),
      fileName: text(document.file_name) || null,
      wordCount,
      sentenceCount: Math.max(0, Math.round(wordCount / 20)),
      pageCount,
      overallCoverage,
      sufficientForScoring: !notScored,
      ocrPages,
      tablesDetected: number(document.table_count),
      imagesDetected: number(document.image_count),
      categoryCoverage: categoryScores.map((category) => {
        const criteria = detailedScores.filter((item) => item.category === category.name);
        const detected = criteria.filter((item) => item.released && item.evidence.length > 0).length;
        return {
          name: category.name,
          coverage: criteria.length ? detected / criteria.length : 0,
          detectedCriteria: detected,
          totalCriteria: criteria.length,
        };
      }),
      contentFingerprint: text(document.content_hash, text(response.input_checksum, "not available")),
    },
    priorProjectCheck: {
      highestSimilarity: number(priorProject.highest_similarity),
      checkedProjects: number(priorProject.checked_projects),
      level: text(priorProject.level, "not_run"),
      matches: array(priorProject.matches).map((rawMatch) => {
        const match = record(rawMatch);
        return {
          id: text(match.proposal_id, text(match.proposal_version_id)),
          title: text(match.title, "Prior proposal"),
          similarity: number(match.similarity),
        };
      }),
    },
    calibration: {
      applied: boolean(validation.official_decision_validated, false),
      note: boolean(validation.official_decision_validated, false)
        ? "The model has been validated against held-out expert decisions."
        : `${text(validation.evaluation_scope, "Bootstrap validation only")}. `
          + "Metrics measure recovery of weak labels, not real MoC/CMPDI decision accuracy.",
      sampleSize: number(validation.test_rows),
      meanAbsoluteError: number(validation.total_score_mae),
      scoreFactor: 1,
    },
    detailedScores,
    categoryScores,
    finalRecommendation,
    strengths: strengths.length ? strengths : ["No released criterion reached the recorded strength threshold."],
    weaknesses: [...weaknesses, ...unresolved].slice(0, 10),
    riskAreas,
    improvementSuggestions,
    humanReview: {
      required: true,
      reasons: [
        !gateAccepted ? `Document gate: ${gateReasonText || titleCase(gateStatus)}.` : "",
        notScored ? "No official automated score was released." : "The trained score is advisory and requires expert confirmation.",
        ...abstentionReasons.slice(0, 3),
        ...failedReasons.slice(0, 3),
      ].filter(Boolean),
      priority: !gateAccepted || hasHardFailure || notScored ? "high" : "standard",
      minimumReviewers: 2,
      completedReviews: 0,
      status: "pending",
    },
  };
}
