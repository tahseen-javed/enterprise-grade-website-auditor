// R2 helpers for generated reports and exports. Replaces the local
// data/reports and data/exports folders — R2 has no ephemeral-filesystem
// problem across redeploys/restarts, which local disk on a Worker would.

export function reportKey(jobId: number, businessId: number, businessName: string): string {
  const slug = (businessName || "business").replace(/[^A-Za-z0-9]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase().slice(0, 60) || "business";
  return `reports/job_${jobId}/${String(businessId).padStart(6, "0")}-${slug}.html`;
}

export async function putReport(bucket: R2Bucket, key: string, html: string): Promise<void> {
  await bucket.put(key, html, { httpMetadata: { contentType: "text/html; charset=utf-8" } });
}

export async function getReport(bucket: R2Bucket, key: string): Promise<R2ObjectBody | null> {
  return bucket.get(key);
}

export async function deleteJobReports(bucket: R2Bucket | undefined, jobId: number): Promise<number> {
  if (!bucket) return 0;
  let removed = 0;
  let cursor: string | undefined;
  try {
    do {
      const listing = await bucket.list({ prefix: `reports/job_${jobId}/`, cursor });
      for (const obj of listing.objects) {
        await bucket.delete(obj.key);
        removed += 1;
      }
      cursor = listing.truncated ? listing.cursor : undefined;
    } while (cursor);
  } catch {
    /* storage may be temporarily unavailable; the D1 rows are still deleted by the caller */
  }
  return removed;
}
