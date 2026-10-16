"use client";

import { useRouter } from "next/navigation";
import SearchForm from "@/app/search/search-form";

export default function HomeSearch() {
  const router = useRouter();
  return <SearchForm compact isLoading={false} onSearch={(values) => router.push(`/search?${new URLSearchParams(values)}`)} />;
}
