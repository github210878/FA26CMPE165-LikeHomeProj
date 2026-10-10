"use client";

import { useState } from "react";
import Link from "next/link";
import type { HotelSearchResult } from "@/lib/api-types";
import { getHotelThumbnailUrl } from "@/lib/hotel-thumbnail";

const dollarAmount = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

export default function HotelResultCard({ hotel, checkoutHref }: { hotel: HotelSearchResult; checkoutHref?: string | null }) {
  const [failedThumbnail, setFailedThumbnail] = useState<string | null>(null);
  const thumbnail = getHotelThumbnailUrl(hotel.thumbnail);
  const name = hotel.name?.trim() || "Unnamed property";
  const price = typeof hotel.price_per_night === "number" && Number.isFinite(hotel.price_per_night) && hotel.price_per_night >= 0
    ? hotel.price_per_night : null;
  const rating = typeof hotel.rating === "number" && Number.isFinite(hotel.rating) && hotel.rating >= 0 && hotel.rating <= 5
    ? hotel.rating : null;
  const amenities = (hotel.amenities ?? []).filter((amenity) => typeof amenity === "string" && amenity.trim())
    .map((amenity) => amenity.trim()).slice(0, 5);

  return (
    <article className="h-full min-w-0 rounded-xl border border-slate-200 bg-white p-5">
      <div className="mb-4 aspect-video overflow-hidden rounded-lg bg-slate-100">
        {thumbnail && failedThumbnail !== thumbnail ? (
          // Provider image hosts vary, so Next.js remote image allowlisting is not suitable here.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={thumbnail}
            alt={`Hotel thumbnail for ${name}`}
            loading="lazy"
            decoding="async"
            width={640}
            height={360}
            className="h-full w-full object-cover"
            onError={() => setFailedThumbnail(thumbnail)}
          />
        ) : (
          <div role="img" aria-label={`No image available for ${name}`} className="flex h-full items-center justify-center px-3 text-center text-sm text-slate-600">
            No image available
          </div>
        )}
      </div>
      <h3 className="break-words text-lg font-semibold text-slate-950">
        {name}
      </h3>
      {price === null ? (
        <p className="mt-2 text-sm text-slate-600">Price unavailable</p>
      ) : (
        <p className="mt-2 text-sm text-slate-700">
          From {dollarAmount.format(price)} / night
        </p>
      )}
      {rating !== null && (
        <p className="mt-1 text-sm text-slate-700">Rating: {rating} / 5</p>
      )}
      {amenities.length > 0 && (
        <p className="mt-2 break-words text-sm text-slate-600">
          {amenities.join(" · ")}
        </p>
      )}
      {checkoutHref && (
        <Link href={checkoutHref} prefetch={false} className="mt-5 inline-flex min-h-11 items-center rounded-md bg-teal-700 px-4 font-medium text-white hover:bg-teal-800">
          Select stay
        </Link>
      )}
    </article>
  );
}
