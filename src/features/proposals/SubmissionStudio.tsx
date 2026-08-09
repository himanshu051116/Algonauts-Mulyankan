import { FormEvent, useMemo, useState } from "react";
import {
  CheckCircle2,
  FileCheck2,
  FileText,
  Loader2,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { extractDocumentPreview } from "../../lib/document-extractor";
import * as api from "../../lib/api";

type Requirement = {
  id: string;
  label: string;
  description: string;
  documentRole: string;
  allowedExtensions: string[];
  mandatory: boolean;
  maxSizeMb: number;
};

const AVAILABLE_SCHEMES = [{ code: "MOC-ST", name: "Ministry of Coal S&T" }];

const PACKAGE_REQUIREMENTS: Requirement[] = [
  {
    id: "proposal_body",
    label: "Proposal body",
    description: "Main technical proposal containing the complete project narrative.",
    documentRole: "main_proposal",
    allowedExtensions: ["pdf", "docx"],
    mandatory: true,
    maxSizeMb: 50,
  },
  {
    id: "budget_sheet",
    label: "Budget estimate sheet",
    description: "Detailed head-wise budget and justification.",
    documentRole: "budget_annexure",
    allowedExtensions: ["pdf", "docx"],
    mandatory: true,
    maxSizeMb: 10,
  },
  {
    id: "pi_cv",
    label: "PI curriculum vitae",
    description: "Qualifications, relevant experience, projects, and publications.",
    documentRole: "pi_cv",
    allowedExtensions: ["pdf", "docx"],
    mandatory: true,
    maxSizeMb: 5,
  },
  {
    id: "endorsement_letter",
    label: "Institutional endorsement",
    description: "Endorsement from the authorised head of institution.",
    documentRole: "institution_profile",
    allowedExtensions: ["pdf", "docx"],
    mandatory: true,
    maxSizeMb: 5,
  },
  {
    id: "declaration_form",
    label: "Declaration and undertaking",
    description: "Signed non-duplication and conflict disclosure declaration.",
    documentRole: "compliance_document",
    allowedExtensions: ["pdf"],
    mandatory: true,
    maxSizeMb: 2,
  },
  {
    id: "prior_funding_declaration",
    label: "Prior funding declaration",
    description: "Declaration of prior or concurrent funding for related work.",
    documentRole: "compliance_document",
    allowedExtensions: ["pdf", "docx"],
    mandatory: true,
    maxSizeMb: 5,
  },
  {
    id: "co_pi_cv",
    label: "Co-PI curriculum vitae",
    description: "Optional CV of co-principal investigators.",
    documentRole: "team_cv",
    allowedExtensions: ["pdf", "docx"],
    mandatory: false,
    maxSizeMb: 5,
  },
  {
    id: "dgms_approval",
    label: "DGMS approval",
    description: "Optional statutory approval where applicable.",
    documentRole: "compliance_document",
    allowedExtensions: ["pdf"],
    mandatory: false,
    maxSizeMb: 5,
  },
  {
    id: "industry_letter",
    label: "Industry partner letter",
    description: "Optional support or deployment commitment from an industry partner.",
    documentRole: "industry_support_letter",
    allowedExtensions: ["pdf", "docx"],
    mandatory: false,
    maxSizeMb: 5,
  },
];

const MANDATORY_REQUIREMENTS = PACKAGE_REQUIREMENTS.filter((item) => item.mandatory);

function errorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

function extensionOf(fileName: string) {
  return fileName.split(".").pop()?.toLowerCase() ?? "";
}

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function contentTypeFor(file: File) {
  if (file.type) return file.type;
  return extensionOf(file.name) === "pdf"
    ? "application/pdf"
    : "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
}

export function SubmissionStudio({
  onComplete,
}: {
  onComplete: () => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [schemeCode, setSchemeCode] = useState("MOC-ST");
  const [files, setFiles] = useState<Record<string, File>>({});
  const [rolesConfirmed, setRolesConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [pendingQueueProposalId, setPendingQueueProposalId] = useState<
    string | null
  >(null);

  const attachedMandatoryCount = MANDATORY_REQUIREMENTS.filter(
    (item) => Boolean(files[item.id]),
  ).length;
  const missingMandatory = MANDATORY_REQUIREMENTS.filter((item) => !files[item.id]);

  const completeness = useMemo(() => {
    const detailsScore =
      (title.trim().length >= 8 ? 15 : 0) +
      (description.trim().length >= 80 ? 15 : 0);
    const attachmentScore = Math.round(
      (attachedMandatoryCount / MANDATORY_REQUIREMENTS.length) * 60,
    );
    return Math.min(100, detailsScore + attachmentScore + (rolesConfirmed ? 10 : 0));
  }, [attachedMandatoryCount, description, rolesConfirmed, title]);

  const selectFile = (requirement: Requirement, candidate: File | null) => {
    setError("");
    if (!candidate) return;
    const extension = extensionOf(candidate.name);
    if (!requirement.allowedExtensions.includes(extension)) {
      setError(
        `${requirement.label} must be ${requirement.allowedExtensions
          .map((item) => item.toUpperCase())
          .join(" or ")}.`,
      );
      return;
    }
    if (candidate.size <= 0) {
      setError(`${requirement.label} is empty.`);
      return;
    }
    if (candidate.size > requirement.maxSizeMb * 1024 * 1024) {
      setError(`${requirement.label} exceeds ${requirement.maxSizeMb} MB.`);
      return;
    }
    setFiles((current) => ({ ...current, [requirement.id]: candidate }));
    setRolesConfirmed(false);
  };

  const removeFile = (requirementId: string) => {
    setFiles((current) => {
      const next = { ...current };
      delete next[requirementId];
      return next;
    });
    setRolesConfirmed(false);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setProgress("");

    if (pendingQueueProposalId) {
      setLoading(true);
      try {
        setProgress("Retrying the evaluation queue...");
        await api.submitProposal(pendingQueueProposalId);
        setPendingQueueProposalId(null);
        setProgress("The sealed package is queued for preliminary evaluation.");
        await onComplete();
      } catch (submitError) {
        setError(errorMessage(submitError));
        setProgress("");
      } finally {
        setLoading(false);
      }
      return;
    }

    if (title.trim().length < 8) {
      setError("Use a clear proposal title of at least 8 characters.");
      return;
    }
    if (description.trim().length < 40) {
      setError("Add an executive summary of at least 40 characters.");
      return;
    }
    if (missingMandatory.length > 0) {
      setError(
        `Attach all mandatory package documents: ${missingMandatory
          .map((item) => item.label)
          .join(", ")}.`,
      );
      return;
    }
    if (!rolesConfirmed) {
      setError("Confirm that each file is assigned to the correct document role.");
      return;
    }

    setLoading(true);
    try {
      setProgress("Checking service availability…");
      const backendAvailable = await api.checkHealth();
      if (!backendAvailable) throw new Error("The service is not reachable right now.");

      const mainFile = files.proposal_body;
      setProgress("Validating the main proposal structure locally…");
      try {
        await extractDocumentPreview(mainFile, { onProgress: setProgress });
      } catch {
        setProgress("Preview unavailable. The document will be validated during submission.");
      }

      setProgress("Creating the governed proposal package…");
      const proposal = await api.createProposal(
        title.trim(),
        schemeCode,
        description.trim(),
      );

      const selected = PACKAGE_REQUIREMENTS.filter((item) => Boolean(files[item.id]));
      for (const [index, requirement] of selected.entries()) {
        const file = files[requirement.id];
        setProgress(
          `Uploading ${index + 1} of ${selected.length}: ${requirement.label}…`,
        );
        const { upload_url, upload_session_id } = await api.getUploadUrl(
          proposal.id,
          file.name,
          file.size,
          requirement.documentRole,
          requirement.id,
        );
        const uploadResponse = await fetch(upload_url, {
          method: "PUT",
          body: file,
          headers: { "Content-Type": contentTypeFor(file) },
        });
        if (!uploadResponse.ok) {
          throw new Error(
            `${requirement.label} upload failed with status ${uploadResponse.status}.`,
          );
        }
        await api.confirmUpload(upload_session_id);
      }

      setProgress("Confirming document roles and sealing the package manifest…");
      const packageResult = await api.confirmSubmissionPackage(proposal.id);
      if (!packageResult.ready_to_confirm || !packageResult.package_hash) {
        throw new Error("The package could not be confirmed as complete.");
      }

      setProgress("Submitting the sealed package for preliminary evaluation…");
      setPendingQueueProposalId(proposal.id);
      await api.submitProposal(proposal.id);
      setPendingQueueProposalId(null);
      setProgress(
        "Submission package confirmed and queued. Preliminary evaluation is running.",
      );
      await onComplete();
    } catch (submitError) {
      setError(errorMessage(submitError));
      setProgress("");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="studio-layout">
      <form className="panel studio-form" onSubmit={submit}>
        <div className="panel-heading">
          <div>
            <span>GOVERNED SUBMISSION PACKAGE</span>
            <h2>Coal R&amp;D proposal</h2>
          </div>
          <FileCheck2 size={24} aria-hidden="true" />
        </div>

        <div className="section-label">1. Funding scheme</div>
        <div className="scheme-grid">
          {AVAILABLE_SCHEMES.map((scheme) => (
            <button
              type="button"
              key={scheme.code}
              className={`scheme-card ${schemeCode === scheme.code ? "selected" : ""}`}
              onClick={() => setSchemeCode(scheme.code)}
              aria-pressed={schemeCode === scheme.code}
            >
              <span>{scheme.code}</span>
              <strong>{scheme.name}</strong>
              <small>Coal science and technology proposal framework</small>
            </button>
          ))}
        </div>

        <div className="section-label">2. Proposal details</div>
        <div className="form-grid">
          <label className="full">
            <span className="field-heading">
              Proposal title <small>{title.length}/160</small>
            </span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value.slice(0, 160))}
              placeholder="e.g. Autonomous mine safety monitoring system"
              minLength={8}
              maxLength={160}
              autoComplete="off"
              required
            />
          </label>
          <label className="full">
            <span className="field-heading">
              Executive summary <small>{description.length}/2000</small>
            </span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value.slice(0, 2000))}
              placeholder="Summarise the problem, proposed solution, expected impact, budget, timeline, and implementation approach."
              rows={6}
              minLength={40}
              maxLength={2000}
              required
            />
          </label>
        </div>

        <div className="section-label">3. Package documents</div>
        <p className="package-guidance">
          Each file is bound to a governed requirement. Mandatory files must be
          complete before the package can be sealed and submitted.
        </p>
        <div className="package-document-grid">
          {PACKAGE_REQUIREMENTS.map((requirement) => {
            const file = files[requirement.id];
            const inputId = `package-${requirement.id}`;
            return (
              <div
                className={`package-document-card ${file ? "has-file" : ""}`}
                key={requirement.id}
              >
                <div className="package-document-heading">
                  <FileText size={19} aria-hidden="true" />
                  <div>
                    <strong>{requirement.label}</strong>
                    <span>{requirement.mandatory ? "Mandatory" : "Optional"}</span>
                  </div>
                </div>
                <p>{requirement.description}</p>
                <small>
                  {requirement.allowedExtensions
                    .map((item) => item.toUpperCase())
                    .join(" / ")} · Maximum {requirement.maxSizeMb} MB
                </small>
                {file ? (
                  <div className="package-file-selected">
                    <CheckCircle2 size={17} aria-hidden="true" />
                    <div>
                      <strong>{file.name}</strong>
                      <span>{formatFileSize(file.size)}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeFile(requirement.id)}
                      aria-label={`Remove ${requirement.label}`}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ) : (
                  <label className="package-file-picker" htmlFor={inputId}>
                    <Upload size={17} aria-hidden="true" />
                    Select document
                    <input
                      id={inputId}
                      type="file"
                      accept={requirement.allowedExtensions
                        .map((item) => `.${item}`)
                        .join(",")}
                      onChange={(event) =>
                        selectFile(requirement, event.target.files?.[0] ?? null)
                      }
                    />
                  </label>
                )}
              </div>
            );
          })}
        </div>

        <label className="package-confirmation">
          <input
            type="checkbox"
            checked={rolesConfirmed}
            onChange={(event) => setRolesConfirmed(event.target.checked)}
          />
          <span>
            I confirm that every selected file is assigned to the correct document
            requirement and is part of this proposal version.
          </span>
        </label>

        <div className="form-feedback" aria-live="polite">
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          {progress && (
            <div className="alert progress" role="status">
              {loading && <Loader2 className="spin" size={17} />}
              {progress}
            </div>
          )}
        </div>

        <button className="primary-button submit-button" disabled={loading} type="submit">
          {loading ? (
            <Loader2 className="spin" size={19} />
          ) : pendingQueueProposalId ? (
            <RotateCcw size={19} />
          ) : (
            <Sparkles size={19} />
          )}
          {loading
            ? pendingQueueProposalId
              ? "Retrying queue"
              : "Processing package"
            : pendingQueueProposalId
              ? "Retry evaluation queue"
              : "Seal package and run scrutiny"}
        </button>
        <div className="prototype-notice">
          <ShieldCheck size={16} />
          <span>
            Automated scrutiny is advisory. Do not upload sensitive or classified
            information to this prototype deployment.
          </span>
        </div>
      </form>

      <aside className="studio-aside" aria-label="Submission package readiness">
        <div className="panel completeness-card">
          <span>PACKAGE READINESS</span>
          <div className="readiness-score">
            <strong>{completeness}</strong>
            <small>%</small>
          </div>
          <div
            className="progress-track"
            role="progressbar"
            aria-label="Submission package readiness"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={completeness}
          >
            <i style={{ width: `${completeness}%` }} />
          </div>
          <p>
            {missingMandatory.length === 0
              ? "All mandatory document slots are populated. Confirm the declared roles to seal the package."
              : `${missingMandatory.length} mandatory document slot${
                  missingMandatory.length === 1 ? " is" : "s are"
                } still missing.`}
          </p>
        </div>
        <div className="panel checklist-card readiness-checklist">
          <h3>Mandatory package checklist</h3>
          {MANDATORY_REQUIREMENTS.map((item) => (
            <div className={files[item.id] ? "complete" : ""} key={item.id}>
              <CheckCircle2 size={17} />
              <span>{item.label}</span>
            </div>
          ))}
          <div className={rolesConfirmed ? "complete" : ""}>
            <CheckCircle2 size={17} />
            <span>Document roles confirmed</span>
          </div>
        </div>
        <div className="security-note">
          <ShieldCheck size={19} />
          <div>
            <strong>Immutable package identity</strong>
            <p>
              Mulyankan records a secure identity for the confirmed package. Any
              later file replacement requires the package to be sealed again.
            </p>
          </div>
        </div>
      </aside>
    </div>
  );
}
