import { redirect } from "next/navigation";
import { DEMO_SCENE_ID } from "@/lib/api";

export default function Index() {
  redirect(`/scenes/${DEMO_SCENE_ID}`);
}
