import { useQuery } from "@tanstack/react-query";
import { fetchAnnotations, fetchManifest, fetchSplatUrl } from "@/lib/api";

const POLL_MS = 2000;

export function useScene(sceneId: string) {
  const manifest = useQuery({
    queryKey: ["manifest", sceneId],
    queryFn: () => fetchManifest(sceneId),
    refetchInterval: (q) =>
      q.state.data?.status === "ready" || q.state.data?.status === "failed"
        ? false
        : POLL_MS,
  });

  const ready = manifest.data?.status === "ready";

  const annotations = useQuery({
    queryKey: ["annotations", sceneId],
    queryFn: () => fetchAnnotations(sceneId),
    enabled: ready,
  });

  const splatUrl = useQuery({
    queryKey: ["splatUrl", sceneId],
    queryFn: () => fetchSplatUrl(sceneId),
    enabled: ready,
  });

  return { manifest, annotations, splatUrl, ready };
}
