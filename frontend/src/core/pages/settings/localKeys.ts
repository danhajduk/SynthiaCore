export const LS_API_BASE_KEY = "synthia_api_base";

export function defaultApiBase(): string {
  const host = window.location.hostname || "localhost";
  return `http://${host}:9001`;
}
