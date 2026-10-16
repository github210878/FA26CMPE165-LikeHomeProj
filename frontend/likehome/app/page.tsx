import Image from "next/image";
import Link from "next/link";
import { HiOutlineArrowRight } from "react-icons/hi2";
import HomeSearch from "@/components/HomeSearch";

const destinations = [
  { name: "Los Angeles", image: "los-angeles", description: "City lights & sunny days" },
  { name: "San Francisco", image: "san-francisco", description: "Bay views & neighborhood charm" },
  { name: "Seattle", image: "seattle", description: "Waterfront walks & city views" },
  { name: "Santorini", image: "santorini", description: "Island views & slower mornings" },
];

export default function Home() {
  return (
    <>
      <section className="getaway-hero">
        <Image src="/images/lakeside-cabin.jpg" alt="A wooden cabin balcony overlooking a turquoise lake and forested mountains" fill priority sizes="100vw" className="object-cover object-center" />
        <div className="absolute inset-0 bg-gradient-to-r from-black/65 via-black/35 to-black/10" />
        <div className="site-container relative z-10 pb-10 pt-14 sm:pb-12 sm:pt-20">
          <h1 className="max-w-2xl text-5xl font-semibold leading-[1.04] tracking-tight text-white sm:text-6xl lg:text-7xl">Find your next<br />getaway.</h1>
          <p className="mt-6 max-w-lg text-base leading-7 text-white/95 sm:text-lg">Search hotels, compare prices, and find a place that feels like home.</p>
          <div className="mt-10 sm:mt-14"><HomeSearch /></div>
        </div>
      </section>
      <section id="destinations" className="site-container py-9 sm:py-11">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div><h2 className="text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">Where will you go next?</h2><p className="mt-2 text-sm text-slate-600">A few places to inspire your next stay.</p></div>
          <Link href="/search" className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-teal-800">Explore all stays <HiOutlineArrowRight aria-hidden="true" /></Link>
        </div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {destinations.map((destination) => (
            <Link key={destination.name} href={`/search?destination=${encodeURIComponent(destination.name)}`} className="destination-card group">
              <Image src={`/images/${destination.image}.jpg`} alt="" fill sizes="(max-width: 1023px) 50vw, 25vw" className="object-cover transition-transform duration-300 group-hover:scale-105" />
              <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/10 to-transparent" />
              <div className="absolute inset-x-0 bottom-0 p-4 sm:p-5"><h3 className="text-base font-semibold text-white sm:text-lg">{destination.name}</h3><p className="mt-1 text-xs leading-5 text-white/90">{destination.description}</p></div>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
