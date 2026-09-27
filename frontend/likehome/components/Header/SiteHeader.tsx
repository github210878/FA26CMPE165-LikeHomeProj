import { navLinks } from "@/constants/constant";
import { link } from "fs";
import Link from "next/link";
import React from "react";
import { HiBars3BottomRight } from "react-icons/hi2";

type things = {
  openHead: () => void;
};

const SiteHeader = ({openHead}:things) => {
  return (
    //<div className="transition-all duration=200 h-[12vh] z-[100] fixed w-full">
    <header className="flex border-b border-slate-200 bg-white">

      {/*Nav Links*/} {/**lg:flex */}
      <div className="inline-flex  mx-auto flex h-full w-[90%] xl:w-[80%] justify-between">

        <Link
          href="/"
          className="inline-flex min-h-16 shrink-0 self-start items-center rounded-sm px-2 text-xl font-semibold tracking-tight text-slate-950"
        >
          LikeHome
        </Link>

        {/*<input className="short-placeholder" type="search" autocomplete="off" placeholder="Home?"></input>
        */}

        <div className="hidden lg:flex items-center space-x-10">
          {navLinks.map((link) => {
            return (
              <Link
                href={link.url}
                key={link.id}
                className="text-black hover:text-teal-500 font-semibol transition-all duration-200"
              >
                <p>{link.label}</p>
              </Link>
            );
          })}
        </div>
        {/** Burger menu */}
        <HiBars3BottomRight onClick={openHead} className="lg:hidden w-8 h-auto cursor-pointer text-black" />


        {/*
        <nav aria-label="Primary navigation" className="w-full min-w-0 sm:w-auto">
          <ul className="flex flex-wrap items-center gap-x-1 text-sm sm:justify-end sm:gap-x-2">
            <li>
              <Link
                href="/"
                className="inline-flex min-h-11 items-center whitespace-nowrap rounded-sm px-2 font-medium text-slate-700 transition-colors hover:text-slate-950"
              >
                Home
              </Link>
            </li>
            <li>
              <span className="inline-flex min-h-11 items-center whitespace-nowrap px-2 text-slate-500">
                Find a Stay
                <span className="sr-only"> (coming soon)</span>
              </span>
            </li>
            <li>
              <span className="inline-flex min-h-11 items-center whitespace-nowrap px-2 text-slate-500">
                My Bookings
                <span className="sr-only"> (coming soon)</span>
              </span>
            </li>
            <li>
              <span className="inline-flex min-h-11 items-center whitespace-nowrap px-2 text-slate-500">
                Sign In
                <span className="sr-only"> (coming soon)</span>
              </span>
            </li>
            <li>
              <Link href="/signup" className="inline-flex min-h-11 items-center whitespace-nowrap rounded-md bg-teal-700 px-3 font-medium text-white transition-colors hover:bg-teal-800">
                Sign Up
              </Link>
            </li>
          </ul>
        </nav>*/}
      </div>
    </header >
  );
}
export default SiteHeader;