import {
  GetObjectCommand,
  ListObjectsV2Command,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

const R2_ACCOUNT_ID = process.env.R2_ACCOUNT_ID ?? "";
const R2_ACCESS_KEY_ID = process.env.R2_ACCESS_KEY_ID ?? "";
const R2_SECRET_ACCESS_KEY = process.env.R2_SECRET_ACCESS_KEY ?? "";
const R2_UPLOADS_BUCKET = process.env.R2_UPLOADS_BUCKET ?? "";
export const R2_ARTIFACTS_BUCKET = process.env.R2_ARTIFACTS_BUCKET ?? "";

export const r2Configured = Boolean(
  R2_ACCOUNT_ID && R2_ACCESS_KEY_ID && R2_SECRET_ACCESS_KEY && R2_UPLOADS_BUCKET,
);

const client: S3Client | null = r2Configured
  ? new S3Client({
      region: "auto",
      endpoint: `https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
      credentials: {
        accessKeyId: R2_ACCESS_KEY_ID,
        secretAccessKey: R2_SECRET_ACCESS_KEY,
      },
    })
  : null;

export async function presignPut(
  key: string,
  contentType: string,
  expiresInSeconds: number,
): Promise<string> {
  if (!client) throw new Error("R2 not configured");
  const cmd = new PutObjectCommand({
    Bucket: R2_UPLOADS_BUCKET,
    Key: key,
    ContentType: contentType,
  });
  return getSignedUrl(client, cmd, { expiresIn: expiresInSeconds });
}

export async function putArtifactJson(key: string, value: unknown): Promise<void> {
  if (!client || !R2_ARTIFACTS_BUCKET) return;
  await client.send(
    new PutObjectCommand({
      Bucket: R2_ARTIFACTS_BUCKET,
      Key: key,
      Body: JSON.stringify(value),
      ContentType: "application/json",
    }),
  );
}

export async function getArtifactJson<T>(key: string): Promise<T | null> {
  if (!client || !R2_ARTIFACTS_BUCKET) return null;
  try {
    const out = await client.send(
      new GetObjectCommand({ Bucket: R2_ARTIFACTS_BUCKET, Key: key }),
    );
    if (!out.Body) return null;
    const text = await out.Body.transformToString();
    return JSON.parse(text) as T;
  } catch (err) {
    const e = err as { name?: string; $metadata?: { httpStatusCode?: number } };
    if (e?.name === "NoSuchKey" || e?.$metadata?.httpStatusCode === 404) return null;
    throw err;
  }
}

export async function listSceneIds(): Promise<string[]> {
  if (!client || !R2_ARTIFACTS_BUCKET) return [];
  const ids = new Set<string>();
  let token: string | undefined;
  do {
    const out = await client.send(
      new ListObjectsV2Command({
        Bucket: R2_ARTIFACTS_BUCKET,
        Prefix: "scenes/",
        Delimiter: "/",
        ContinuationToken: token,
      }),
    );
    for (const p of out.CommonPrefixes ?? []) {
      const k = p.Prefix ?? "";
      const id = k.replace(/^scenes\//, "").replace(/\/$/, "");
      if (id) ids.add(id);
    }
    token = out.IsTruncated ? out.NextContinuationToken : undefined;
  } while (token);
  return [...ids];
}

export async function getArtifactBytes(key: string): Promise<Buffer | null> {
  if (!client || !R2_ARTIFACTS_BUCKET) return null;
  try {
    const out = await client.send(
      new GetObjectCommand({ Bucket: R2_ARTIFACTS_BUCKET, Key: key }),
    );
    if (!out.Body) return null;
    const arr = await out.Body.transformToByteArray();
    return Buffer.from(arr);
  } catch (err) {
    const e = err as { name?: string; $metadata?: { httpStatusCode?: number } };
    if (e?.name === "NoSuchKey" || e?.$metadata?.httpStatusCode === 404) return null;
    throw err;
  }
}
