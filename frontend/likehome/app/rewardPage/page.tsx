import type { Metadata } from "next";
import RewardPageExperience from "@/components/RewardPageExperience";

export const metadata: Metadata = {
    title: "Reward points | LikeHome",
};

export default function RewardPage() {
  return <RewardPageExperience />;
}
