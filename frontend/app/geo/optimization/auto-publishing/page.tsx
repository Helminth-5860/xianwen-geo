import { AutoPublishingWorkspace } from "@/components/auto-publishing-workspace";
import { PublicationReviewPanel } from "@/components/publication-review-panel";

export default function AutoPublishingPage() {
  return (
    <>
      <PublicationReviewPanel />
      <AutoPublishingWorkspace />
    </>
  );
}
