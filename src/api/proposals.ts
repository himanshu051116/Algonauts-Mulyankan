import { apiFetch } from "./client";

export interface ProposalResponse {
  id: string;
  title: string;
  scheme_id: string;
  status: string;
  current_version: number;
  owner_id: string;
  executive_summary?: string | null;
  document_id?: string | null;
  document_file_name?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProposalListResponse {
  proposals: ProposalResponse[];
  total: number;
  skip: number;
  limit: number;
}

export interface UploadUrlResponse {
  upload_url: string;
  upload_session_id: string;
  document_id: string;
  storage_path: string;
  expires_in: number;
}


export interface DocumentDownloadResponse {
  document_id: string;
  file_name: string;
  download_url: string;
  expires_in: number;
}

export interface ConfirmUploadResponse {
  document_id: string;
  status: string;
  extraction_status: string;
  word_count: number;
  warnings: string[];
}

export interface SubmissionPackageRequirement {
  id: string;
  label: string;
  description: string;
  document_role: string;
  allowed_types: string[];
  mandatory: boolean;
  max_size_mb: number;
  status: string;
  document_id: string | null;
  reason: string | null;
}

export interface SubmissionPackageDocument {
  id: string;
  requirement_id: string | null;
  document_role: string;
  file_name: string;
  file_type: string;
  file_size: number;
  sha256_hash: string;
  is_primary: boolean;
  role_status: string;
  has_extractable_text: boolean;
  upload_completed: boolean;
  created_at: string | null;
}

export interface SubmissionPackageResponse {
  proposal_id: string;
  proposal_version_id: string;
  proposal_version_number: number;
  scheme_code: string;
  policy_version: string;
  package_status: string;
  package_hash: string | null;
  package_confirmed_at: string | null;
  package_confirmed_by: string | null;
  ready_to_confirm: boolean;
  missing_mandatory_requirements: string[];
  invalid_requirements: string[];
  unassigned_document_ids: string[];
  requirements: SubmissionPackageRequirement[];
  documents: SubmissionPackageDocument[];
}

export async function createProposal(
  title: string,
  schemeCode: string,
  executiveSummary?: string | null,
): Promise<ProposalResponse> {
  return apiFetch<ProposalResponse>("/proposals/", {
    method: "POST",
    body: JSON.stringify({
      title,
      scheme_code: schemeCode,
      executive_summary: executiveSummary?.trim() || null,
    }),
  });
}

export async function listProposals(
  skip = 0,
  limit = 50,
): Promise<ProposalListResponse> {
  return apiFetch<ProposalListResponse>(
    `/proposals/?skip=${skip}&limit=${limit}`,
  );
}

export async function getProposal(
  proposalId: string,
): Promise<ProposalResponse> {
  return apiFetch<ProposalResponse>(`/proposals/${proposalId}`);
}

export async function getUploadUrl(
  proposalId: string,
  fileName: string,
  fileSize: number,
  documentRole = "main_proposal",
  requirementId?: string | null,
): Promise<UploadUrlResponse> {
  return apiFetch<UploadUrlResponse>(`/proposals/${proposalId}/upload-url`, {
    method: "POST",
    body: JSON.stringify({
      file_name: fileName,
      file_size: fileSize,
      document_role: documentRole,
      requirement_id: requirementId ?? null,
    }),
  });
}

export async function getSubmissionPackage(
  proposalId: string,
): Promise<SubmissionPackageResponse> {
  return apiFetch<SubmissionPackageResponse>(
    `/proposals/${proposalId}/submission-package`,
  );
}

export async function confirmSubmissionPackage(
  proposalId: string,
): Promise<SubmissionPackageResponse> {
  return apiFetch<SubmissionPackageResponse>(
    `/proposals/${proposalId}/submission-package/confirm`,
    {
      method: "POST",
      body: JSON.stringify({ confirm_declared_roles: true }),
    },
  );
}

export async function submitProposal(
  proposalId: string,
): Promise<{ id: string; status: string }> {
  return apiFetch<{ id: string; status: string }>(
    `/proposals/${proposalId}/submit`,
    { method: "POST" },
  );
}

export async function confirmUpload(
  uploadSessionId: string,
  checksum?: string | null,
): Promise<ConfirmUploadResponse> {
  return apiFetch<ConfirmUploadResponse>("/storage/confirm-upload", {
    method: "POST",
    body: JSON.stringify({
      upload_session_id: uploadSessionId,
      checksum: checksum ?? null,
    }),
  });
}


export async function getDocumentDownloadUrl(
  documentId: string,
): Promise<DocumentDownloadResponse> {
  return apiFetch<DocumentDownloadResponse>(
    `/storage/documents/${documentId}/download-url`,
  );
}
