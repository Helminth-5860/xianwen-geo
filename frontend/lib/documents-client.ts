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
