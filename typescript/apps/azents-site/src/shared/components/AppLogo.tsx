"use client";

import { rem } from "@mantine/core";
import Image from "next/image";
import Link from "next/link";
import { AZENTS_BRAND } from "@/shared/lib/brand";
import classes from "./AppLogo.module.css";

interface AppLogoProps {
  href?: string;
  width?: number;
}

export function AppLogo({
  href,
  width = 118,
}: AppLogoProps): React.ReactElement {
  const content = (
    <>
      <Image
        alt="Azents"
        className={`${classes.logo} ${classes.darkAsset}`}
        height={861}
        priority
        sizes={`${width / 16}rem`}
        src={AZENTS_BRAND.logoDark}
        style={{ width: rem(width), height: "auto" }}
        width={4096}
      />
      <Image
        alt=""
        className={`${classes.logo} ${classes.lightAsset}`}
        height={861}
        priority
        sizes={`${width / 16}rem`}
        src={AZENTS_BRAND.logoLight}
        style={{ width: rem(width), height: "auto" }}
        width={4096}
      />
    </>
  );

  if (!href) {
    return <span className={classes.root}>{content}</span>;
  }

  return (
    <Link aria-label="Azents" className={classes.root} href={href}>
      {content}
    </Link>
  );
}
