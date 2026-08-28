import { get, post } from "./auth-client";

export type APICredentialEnvironment = "staging" | "production";

export type APICredential = Readonly<{
  id: string;
  provider_key: string;
  provider_name: string;
  environment: APICredentialEnvironment;
  secret_mask: string;
  version_no: number;
  status: "active" | "replaced";
  created_at: string;
}>;

export type APICredentialTestResult = Readonly<{
  credential: APICredential;
  storage_valid: boolean;
  remote_validated: false;
}>;

export const getAPICredentials = () => get<APICredential[]>("/admin/api-credentials");

export const createAPICredential = (input: {
  provider_key: string;
  environment: APICredentialEnvironment;
  api_key: string;
}) => post<APICredential>("/admin/api-credentials", input);

export const rotateAPICredential = (credential: APICredential, apiKey: string) =>
  post<APICredential>(`/admin/api-credentials/${credential.id}/rotate`, {
    expected_version: credential.version_no,
    api_key: apiKey,
  });

export const testAPICredential = (credential: APICredential) =>
  post<APICredentialTestResult>(`/admin/api-credentials/${credential.id}/test`, {
    expected_version: credential.version_no,
  });
