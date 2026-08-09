export type EvaluationStreamId = "coal-energy";

export type EvaluationDisplayStatus =
  | "approved"
  | "revision"
  | "rejected"
  | "not_scored";

export interface EvaluationOutput {
  schemaVersion: string;
  engine: string;
  status: EvaluationDisplayStatus;
  scoringStatus: string;
  totalScore: number | null;
  diagnosticScore: number | null;
  documentGate: {
    status: string;
    accepted: boolean;
    scoringAllowed: boolean;
    documentType: string;
    declaredRole: string;
    classifiedRole: string;
    roleStatus: string;
    structureCoverage: number;
    schemeRelevance: number;
    reasons: string[];
  };
  hardScreening: {
    result: string;
    failedReasons: string[];
    rules: { id: string; passed: boolean; label: string; reason: string; correction?: string }[];
  };
  researchStream: { id: string; name: string; modelProfile: string };
  documentAudit: {
    source: string;
    fileName: string | null;
    wordCount: number;
    sentenceCount: number;
    pageCount: number | null;
    overallCoverage: number;
    sufficientForScoring: boolean;
    ocrPages?: number[];
    tablesDetected?: number;
    imagesDetected?: number;
    categoryCoverage: { name: string; coverage: number; detectedCriteria: number; totalCriteria: number }[];
    contentFingerprint: string;
  };
  priorProjectCheck: {
    highestSimilarity: number;
    checkedProjects: number;
    level: string;
    matches: { id: string; title: string; similarity: number }[];
  };
  calibration: {
    applied: boolean;
    note: string;
    sampleSize: number;
    meanAbsoluteError: number;
    scoreFactor: number;
  };
  detailedScores: {
    key: string;
    criterion: string;
    category: string;
    maximum: number;
    awarded: number | null;
    ordinalGrade: number | null;
    criterionStatus: string;
    released: boolean;
    evidenceCount: number;
    missingEvidence: string[];
    evidence: {
      text: string;
      sourcePage?: number | null;
      sourceSection?: string | null;
      documentRole?: string | null;
      verificationStatus?: string | null;
    }[];
  }[];
  categoryScores: { name: string; awarded: number | null; maximum: number; released: boolean }[];
  finalRecommendation: string;
  strengths: string[];
  weaknesses: string[];
  riskAreas: string[];
  improvementSuggestions: string[];
  humanReview: {
    required: boolean;
    reasons: string[];
    priority: string;
    minimumReviewers: number;
    completedReviews: number;
    status: string;
  };
}

export type StreamEvaluationOutput = EvaluationOutput;
