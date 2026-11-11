import { expect, type APIRequestContext } from "@playwright/test";

// Explicit API setup for synthetic fixtures used by unrelated browser workflows.
export async function publishFixtureJob(request: APIRequestContext, headers: Record<string, string>, job: { id: string; version: number }) {
  const response = await request.post(`http://localhost:8001/jobs/recruiter/${job.id}/publication/publish`, {
    headers, data: { expected_version: job.version, rights_confirmed: true, expires_at: new Date(Date.now() + 30 * 86400000).toISOString() },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}
