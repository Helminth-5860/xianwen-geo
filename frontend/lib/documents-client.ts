import { get, getCsrfToken, post, readEnvelope } from "./auth-client";
import { publicEnvironment } from "./env";

export type UploadIntent = Readonly<{
  id: string;
  status: "pending_upload" | "verifying" | "completed" | "rejected" | "expired";
  version: number;
  declared_filename: string;
  declared_file_kind: string;
  declared_size: number;
  expires_at: string;
  stable_error_code: string;
  document_id: string | null;
  document_version_id: string | null;
}>;

export type SubjectDocument = Readonly<{
  id: string;
  document_version_id: string;
  display_name: string;
  detected_file_kind: string;
  size_bytes: number;
  safe_status: "clean";
  download_available: boolean;
  created_at: string;
}>;

type UploadCredential = Readonly<{
  method: "POST";
  url: string;
  fields: Record<string, string>;
  expires_in: number;
}>;

export async function createUploadIntent(subjectId: string, file: File, idempotencyKey: string) {
  return post<{ intent: UploadIntent; upload: UploadCredential | null }>(
    "/files/upload-intents",
    {
      subject_id: subjectId,
      filename: file.name,
      content_type: file.type || "application/octet-stream",
      size_bytes: file.size,
      purpose: "subject_library",
    },
    { "Idempotency-Key": idempotencyKey },
  );
}

export function uploadDirect(
  credential: UploadCredential,
  file: File,
  onProgress: (percent: number) => void,
) {
  return new Promise<void>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", credential.url);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onerror = () => reject(new Error("文件上传失败，请稍后重试"));
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) resolve();
      else reject(new Error("文件上传失败，请稍后重试"));
    };
    const body = new FormData();
    Object.entries(credential.fields).forEach(([key, value]) => body.append(key, value));
    body.append("file", file);
    request.send(body);
  });
}

export const completeUploadIntent = (intent: UploadIntent) =>
  post<UploadIntent>(`/files/upload-intents/${intent.id}/complete`, {
    expected_version: intent.version,
  });

export const getUploadIntent = (id: string) => get<UploadIntent>(`/files/upload-intents/${id}`);

export const getSubjectDocuments = (subjectId: string) =>
  get<{ documents: SubjectDocument[] }>(`/subjects/${subjectId}/documents`);

export async function openDocumentDownload(documentId: string) {
  const csrfToken = await getCsrfToken();
  const response = await fetch(
    `${publicEnvironment.apiBaseUrl}/documents/${documentId}/download-intents`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: "{}",
      cache: "no-store",
    },
  );
  const credential = await readEnvelope<{ url: string; expires_in: number }>(response);
  window.location.assign(credential.url);
}

export function newUploadIdempotencyKey() {
  return crypto.randomUUID();
}

export type DocumentParseJob = Readonly<{
  id: string;
  status: "queued" | "running" | "retry_wait" | "succeeded" | "failed";
  stable_error_code: string;
  created_at: string;
  updated_at: string;
}>;

export type DocumentParseResult = Readonly<{
  status: "not_started" | "queued" | "running" | "retry_wait" | "succeeded" | "failed";
  stable_error_code: string;
  state_version: number | null;
  latest_version: Readonly<{ id: string; version_no: number }> | null;
  current_confirmed_version: Readonly<{ id: string; version_no: number }> | null;
  canonical_text: string;
  tables: ReadonlyArray<ReadonlyArray<ReadonlyArray<string>>>;
  warning_codes: readonly string[];
  confirmed: boolean;
  parser: Readonly<{ key: string; version: string; ocr_engine_version: string }> | null;
}>;

export const requestDocumentParse = (document: SubjectDocument, idempotencyKey: string) =>
  post<DocumentParseJob>(
    `/documents/${document.id}/parse`,
    { document_version_id: document.document_version_id },
    { "Idempotency-Key": idempotencyKey },
  );

export const getDocumentParseResult = (documentId: string) =>
  get<DocumentParseResult>(`/documents/${documentId}/parse-result`);

export const confirmDocumentParse = (
  documentId: string,
  result: DocumentParseResult,
  confirmedText: string,
) => {
  if (result.state_version === null || result.latest_version === null) {
    throw new Error("\u65e0\u6cd5\u8bfb\u53d6\u89e3\u6790\u7ed3\u679c");
  }
  return post<{
    parse_state_version: number;
    confirmed_version: { id: string; version_no: number };
    created: boolean;
  }>(`/documents/${documentId}/confirm`, {
    expected_parse_state_version: result.state_version,
    source_parsed_version_id: result.latest_version.id,
    confirmed_text: confirmedText,
  });
};

export function newParseIdempotencyKey() {
  return crypto.randomUUID();
}
