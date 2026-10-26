import type { Metadata } from "next";
import SearchExperience from "./search-experience";

export const metadata: Metadata = {
  title: "Find a stay | LikeHome",
};

export default async function SearchPage({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const value = (key: string) => typeof query[key] === "string" ? query[key] as string : "";
  const initialSearch = value("destination") ? {
    destination: value("destination"), checkIn: value("checkIn"),
    checkOut: value("checkOut"), guests: value("guests") || "1",
  } : undefined;
  return (
    <SearchExperience key={JSON.stringify(initialSearch)} initialSearch={initialSearch} />
  );
}
