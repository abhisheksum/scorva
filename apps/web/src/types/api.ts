export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy' | 'unknown';

export interface ServiceCheck {
  status: HealthStatus;
  latency_ms?: number;
  details?: string;
}

export interface HealthResponse {
  status: HealthStatus;
  app_name: string;
  environment: string;
  version: string;
  timestamp: string;
  services: Record<string, ServiceCheck>;
}

export interface ApiErrorDetail {
  field?: string;
  issue: string;
  type?: string;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  details: ApiErrorDetail[];
  request_id: string;
  timestamp: string;
}

export interface ApiResponseError {
  error: ApiErrorPayload;
}
