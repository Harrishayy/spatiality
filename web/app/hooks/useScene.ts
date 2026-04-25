import { useQuery } from "@tanstack/react-query";
import { fetchAnnotations, fetchManifest, fetchSplatUrl } from "@/lib/api";

const POLL_MS = 2000;

export function useScene(sceneId: string) {
  const manifest = useQuery({
    queryKey: ["manifest", sceneId],
    queryFn: () => fetchManifest(sceneId),
    // Poll until both top-level pipeline AND segmentation reach a terminal
    // state. We can't stop on status="ready" alone — segmentation may still
    // be running in the background after splat completes.
    refetchInterval: (q) => {
      const m = q.state.data;
      if (!m) return POLL_MS;
      const top = m.status;
      const seg = m.stages.segmentation.status;
      const topDone = top === "ready" || top === "failed";
      const segDone = seg === "complete" || seg === "failed";
      return topDone && segDone ? false : POLL_MS;
    },
  });

  const splatReady = manifest.data?.stages.splat.status === "complete";
  const segReady = manifest.data?.stages.segmentation.status === "complete";

  const annotations = useQuery({
    queryKey: ["annotations", sceneId],
    queryFn: () => fetchAnnotations(sceneId),
    enabled: segReady,
  });

  const splatUrl = useQuery({
    queryKey: ["splatUrl", sceneId],
    queryFn: () => fetchSplatUrl(sceneId),
    enabled: splatReady,
  });

  // Backward-compat: `ready` used to mean "everything ready". Keep it as the
  // narrower "splat is renderable" signal — that's what its only consumer
  // (the page) actually needed.
  return { manifest, annotations, splatUrl, splatReady, segReady, ready: splatReady };
}
