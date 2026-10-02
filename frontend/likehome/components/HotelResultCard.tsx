"use client";

import { useState } from "react";
import type { HotelSearchResult } from "@/lib/api-types";
import { getHotelThumbnailUrl } from "@/lib/hotel-thumbnail";

const dollarAmount = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

export default function HotelResultCard({ hotel }: { hotel: HotelSearchResult }) {
  const [failedThumbnail, setFailedThumbnail] = useState<string | null>(null);
  const thumbnail = getHotelThumbnailUrl(hotel.thumbnail);

  return (
    <article className="h-full min-w-0 rounded-xl border border-slate-200 bg-white p-5">
      <div className="mb-4 aspect-video overflow-hidden rounded-lg bg-slate-100">
        {thumbnail && failedThumbnail !== thumbnail ? (
          // Provider image hosts vary, so Next.js remote image allowlisting is not suitable here.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={thumbnail}
            alt={hotel.name ? `Hotel thumbnail for ${hotel.name}` : "Hotel thumbnail"}
            loading="lazy"
            decoding="async"
            width={640}
            height={360}
            className="h-full w-full object-cover"
            onError={() => setFailedThumbnail(thumbnail)}
          />
        ) : (
          <div className="flex h-full items-center justify-center px-3 text-center text-sm text-slate-600">
            No image available
          </div>
        )}
      </div>
      <h3 className="break-words text-lg font-semibold text-slate-950">
        {hotel.name ?? "Unnamed property"}
      </h3>
      {hotel.price_per_night === null ? (
        <p className="mt-2 text-sm text-slate-600">Price unavailable</p>
      ) : (
        <p className="mt-2 text-sm text-slate-700">
          From {dollarAmount.format(hotel.price_per_night)} per night
        </p>
      )}
      {hotel.rating !== null && (
        <p className="mt-1 text-sm text-slate-700">Rating: {hotel.rating} / 5</p>
      )}
      {hotel.amenities && hotel.amenities.length > 0 && (
        <p className="mt-2 break-words text-sm text-slate-600">
          {hotel.amenities.slice(0, 5).join(" · ")}
        </p>
      )}
    </article>
  );
}
