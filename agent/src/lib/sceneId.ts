import { ulid } from "ulid";

export function newSceneId(): string {
  return ulid().toLowerCase();
}

export function sanitizeFilename(name: string): string {
  const base = name.split(/[/\\]/).pop() ?? "file";
  const cleaned = base.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 200);
  return cleaned || "file";
}
