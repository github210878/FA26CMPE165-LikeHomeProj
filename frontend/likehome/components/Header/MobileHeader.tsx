import Link from "next/link";
import { navLinks } from "@/constants/constant";
import React from "react";
import { CgClose } from "react-icons/cg";

type things = {
  showHead: boolean;
  closeHead: () => void;
}

const MobileHeader = ({ closeHead, showHead }: things) => {
  const headOpen = showHead ? "translate-x-0" : "translate-x-[-100%]";
  return (
    <div>
      {/**Overlay */}
      <div className={`fixed ${headOpen} inset-0 transform transition-all duration-500 z-[1002] bg-black opacity-70 w-full h-screen`}></div>
      {/**Nav Links */}
      <div className={`text-white ${headOpen} fixed justify-center flex flex-col h-full tranform transition-all duration-500 delay-300 w-[80%] sm:w-[60%] bg-teal-500 space-y-6 z-[1050]`}>
        {navLinks.map((link) => {
          return (
            <Link
              href={link.url}
              key={link.id}
            >
              <p className="text-white w-fit text-[20px] ml-12 border-b-[1.5px] pb-1 border-white sm:text-[30px]">
                {link.label}
              </p>
            </Link>
          );
        })}
        {/**close icon */}
        <CgClose onClick={closeHead} className="absolute top-[0.7rem] right-[1.4rem] sm:w-8 sm:h-8 w-6 h-6" />
      </div>
    </div>
  );
};

export default MobileHeader;