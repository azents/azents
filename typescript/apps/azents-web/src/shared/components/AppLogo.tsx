"use client";

/**
 * Shared logo component.
 *
 * Displays Azents wordmark asset. Optionally acts as link.
 */
import { rem } from "@mantine/core";
import Image from "next/image";
import Link from "next/link";
import { AZENTS_BRAND } from "@/shared/lib/brand";
import classes from "./AppLogo.module.css";

interface AppLogoProps {
  /** Link target URL. When not specified, displays text only without link */
  href?: string;
}

export function AppLogo({ href }: AppLogoProps): React.ReactElement {
  const content = (
    <>
      <Image
        src={AZENTS_BRAND.logoDark}
        alt="Azents"
        width={4096}
        height={861}
        sizes="8rem"
        style={{ width: rem(124), height: "auto" }}
        className={`${classes.logo} ${classes.darkAsset}`}
      />
      <Image
        src={AZENTS_BRAND.logoLight}
        alt=""
        width={4096}
        height={861}
        sizes="8rem"
        style={{ width: rem(124), height: "auto" }}
        className={`${classes.logo} ${classes.lightAsset}`}
      />
    </>
  );

  if (!href) {
    return <span className={classes.root}>{content}</span>;
  }

  return (
    <Link href={href} className={classes.root} aria-label="Azents">
      {content}
    </Link>
  );
}
